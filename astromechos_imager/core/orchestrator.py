# astromechos_imager/core/orchestrator.py
"""High-level flash orchestration. Per design spec §3, §5, §6.4."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from astromechos_imager.core.bootpartition import (
    find_first_fat32_partition,
    find_rootfs_partition,
)


def _bootpartition_open(
    platform_io: "PlatformIO",
    physical_drive_id: int,
    mbr_bytes: bytes,
) -> "object | None":
    r"""Parse the MBR, find the FAT32 partition, open it via userspace FAT.

    Returns None if no FAT32 partition is found (so callers can skip
    customize). This is the single monkeypatching point for tests.

    The returned ``RawFatBootPartition`` reads and writes the FAT in
    userspace (pyfatfs over a raw ``\\.\PHYSICALDRIVEn`` handle) — Windows
    never mounts the partition, so the "Format K:?" / "K:\\ is not
    accessible" shell pop-ups can't fire, the customize step never races
    Explorer, and no drive letter is involved (so the bundle physically
    cannot leak to C: — the old letter-detection failure mode is gone by
    construction).
    """
    from astromechos_imager.core.errors import BootPartitionMountError  # noqa: PLC0415
    from astromechos_imager.core.raw_fat_partition import RawFatBootPartition  # noqa: PLC0415
    try:
        layout = find_first_fat32_partition(mbr_bytes)
    except BootPartitionMountError:
        return None
    return RawFatBootPartition.open_on_drive(
        platform_io, physical_drive_id, layout.offset, layout.size,
    )


def _open_rootfs_partition(
    raw_device_path: str,
    mbr_bytes: bytes,
    debugfs_exe: Path,
    e2fsck_exe: Path,
    invoker: list[str] | None = None,
) -> "object | None":
    """Parse the MBR, find the Linux (0x83) partition, and open an ext4 backend.

    Returns None if no Linux partition is found.
    This is the single monkeypatching point for tests.

    On Windows production: ``raw_device_path`` is a Win32 device path
    (``\\\\.\\PHYSICALDRIVEn``). The ext4 backend constructs a device arg of
    the form ``\\\\.\\PHYSICALDRIVEn?offset=N`` which e2fsprogs on WSL
    interprets via the standard ``?offset=N`` syntax.

    On test machines: monkeypatched to return a FakeRootfsPartition directly.
    """
    from astromechos_imager.core.errors import BootPartitionMountError  # noqa: PLC0415
    from astromechos_imager.core.rootfs import Ext4DebugfsBackend  # noqa: PLC0415
    try:
        layout = find_rootfs_partition(mbr_bytes)
    except BootPartitionMountError:
        return None
    return Ext4DebugfsBackend(
        image_path=raw_device_path,
        offset_bytes=layout.offset,
        debugfs_exe=debugfs_exe,
        e2fsck_exe=e2fsck_exe,
        invoker=invoker,
    )


from astromechos_imager.core.customization import FirstbootBundle  # noqa: E402
from astromechos_imager.core.diskwriter import (  # noqa: E402
    DiskWriter,
    DiskWriterProgress,
    verify_readback,
)
from astromechos_imager.core.errors import ImagerError  # noqa: E402
from astromechos_imager.core.imagesource import open_image  # noqa: E402
from astromechos_imager.core.models import (  # noqa: E402
    DiskRef,
    Ed25519Pair,
    FirstbootConfig,
    LinuxAccount,
    Role,
)
from astromechos_imager.core.platform_io import PlatformIO  # noqa: E402

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlashJobResult:
    ok: bool
    bytes_written: int
    source_sha256: str
    error: BaseException | None = None


@dataclass
class FlashJob:
    platform_io: PlatformIO
    image_path: Path
    target: DiskRef
    role: Role
    firstboot_config: FirstbootConfig
    master_pair: Ed25519Pair
    on_progress: Callable[[DiskWriterProgress], None] = field(default=lambda p: None)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    skip_verify: bool = False
    skip_customize: bool = False
    # Phase 5.5.4: optional rootfs personalization
    # When linux_account is None, rootfs personalization is skipped entirely
    # (backward-compatible for callers that only need the FAT32 firstboot bundle).
    linux_account: LinuxAccount | None = None
    ext4_debugfs_exe: Path | None = None
    ext4_e2fsck_exe: Path | None = None

    def run(self) -> FlashJobResult:
        # PHASE 0 native shell-quiet: set THIS worker thread's error mode
        # (SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX) via
        # astro_flash.dll so any shell error dialog OUR process would
        # raise while touching the half-written removable device — the
        # "K:\ is not accessible" box during the customize step's file
        # I/O — is suppressed for the lifetime of this thread. (The
        # separate "Format K:?" dialog is Explorer's own; SHChangeNotify
        # in lock_and_dismount targets that one.) No-op without the DLL.
        try:
            from astromechos_imager.platform import native_shell_quiet
            if native_shell_quiet.available():
                native_shell_quiet.quiet_thread()
        except Exception:
            pass
        # Audit High #15: lock_and_dismount handles MUST be closed. They are
        # now HELD (locked) for the entire flash — the Win32DiskImager /
        # rpi-imager model — and the outer `finally` closes them at the very
        # end (closing releases each FSCTL_LOCK_VOLUME → Windows remounts the
        # freshly-written card). Holding the lock is what authorises raw
        # in-partition writes (no ERROR_ACCESS_DENIED) AND keeps the volume
        # un-mountable (no "Format K:?" pop-up), with no partition-table
        # surgery.
        locked_handles: list[int] = []
        write_result = None
        try:
            try:
                # 1. Lock + dismount every volume on this physical drive
                #    (lettered AND letterless, found by GUID) and KEEP the
                #    locks held for the whole flash. Passing the physical
                #    drive id lets us lock a volume even when Windows assigned
                #    no drive letter.
                locked_handles = list(
                    self.platform_io.lock_and_dismount(
                        self.target.drive_letters,
                        self.target.physical_drive_id,
                    ) or []
                )
                # 2. Open ONE raw device handle (NO_BUFFERING | WRITE_THROUGH |
                #    SEQUENTIAL_SCAN) and use it for write, verify AND the final
                #    MBR write — rpi-imager's exact model. NO_BUFFERING reads
                #    bypass the OS page cache, and verify reads land in a
                #    4096-aligned buffer (see _Win32RawDevice.read), so the
                #    post-write read-back reads the device truth on the first
                #    pass instead of stale bridge-cached bytes.
                dev = self.platform_io.open_raw_device(self.target.physical_drive_id)
                _log.info("FlashJob START role=%s phys_id=%s image=%s skip_verify=%s "
                          "skip_customize=%s linux_account=%s",
                          getattr(self.role, "value", self.role),
                          self.target.physical_drive_id, self.image_path.name,
                          self.skip_verify, self.skip_customize,
                          "set" if self.linux_account else "none")
                try:
                    _log.info("PHASE streaming-write: starting")
                    with open_image(self.image_path) as src:
                        dw = DiskWriter(src, dev, on_progress=self.on_progress,
                                        cancel_event=self.cancel_event)
                        write_result = dw.run()
                    _log.info("PHASE streaming-write: done — %d bytes, sha256=%s",
                              write_result.bytes_written,
                              write_result.source_sha256[:16])
                    # PrepareForSequentialRead: FlushFileBuffers commits any
                    # in-flight writes; SCSI SYNCHRONIZE_CACHE pushes the USB
                    # bridge's firmware cache to flash. (file_operations_windows
                    # .cpp:1027 + downloadthread.cpp _verify.)
                    dev.flush()
                    self._sync_cache(dev)

                    # 3. Verify on the SAME handle. MBR still absent on disk;
                    #    verify_readback injects the deferred first block in
                    #    memory and reads [first_block_len, length) back via
                    #    aligned NO_BUFFERING reads.
                    if not self.skip_verify and not self.cancel_event.is_set():
                        _log.info("PHASE verify-readback: starting")
                        verify_readback(dev,
                                        expected_sha256=write_result.source_sha256,
                                        length=write_result.bytes_written,
                                        on_progress=self.on_progress,
                                        cancel_event=self.cancel_event,
                                        first_block=write_result.first_block_data)
                        _log.info("PHASE verify-readback: PASSED")

                    # 4. Userspace-FAT customize — runs while the deferred first
                    #    block (the MBR) is STILL ABSENT from the disk. With no
                    #    partition table, Windows cannot discover the FAT32
                    #    partition to auto-mount it: no drive letter, no
                    #    Explorer, no "Format K:?" pop-up. The bundle physically
                    #    cannot reach C: — there is no letter involved.
                    if not self.skip_customize and not self.cancel_event.is_set():
                        _log.info("PHASE customize: starting (userspace FAT)")
                        self.on_progress(DiskWriterProgress(
                            phase="customizing", bytes_done=0, bytes_total=0,
                            throughput_bps=0.0,
                        ))
                        mbr = (write_result.first_block_data[:512]
                               if write_result.first_block_data is not None
                               else dev.read(0, 512))
                        bp = _bootpartition_open(
                            self.platform_io,
                            self.target.physical_drive_id,
                            mbr,
                        )
                        if bp is not None:
                            try:
                                if (
                                    self.linux_account is not None
                                    and not self.cancel_event.is_set()
                                ):
                                    _log.info("PHASE customize: rootfs personalization")
                                    self._run_rootfs_personalization(mbr, bp)
                                if not self.cancel_event.is_set():
                                    _log.info("PHASE customize: firstboot bundle")
                                    FirstbootBundle(self.firstboot_config, self.master_pair).write_to(
                                        bp, self.role)
                            finally:
                                bp.close()
                        _log.info("PHASE customize: done")

                    # 5. Write the deferred first block (the MBR) LAST. Only now
                    #    does the partition table appear on disk, so any Windows
                    #    auto-mount happens AFTER customize — harmless, post-hoc.
                    if (write_result.first_block_data is not None
                            and not self.cancel_event.is_set()):
                        _log.info("PHASE deferred-MBR write")
                        n = dev.write(0, write_result.first_block_data)
                        if n != len(write_result.first_block_data):
                            from astromechos_imager.core.errors import WriteError  # noqa: PLC0415
                            raise WriteError(
                                f"short write of deferred first block: "
                                f"{n}/{len(write_result.first_block_data)}"
                            )
                        dev.flush()
                        self._sync_cache(dev)
                finally:
                    # Safe to close now: DiskWriter.run() unconditionally
                    # joins its producer + consumer threads before it
                    # returns OR raises (t_p.join(); t_c.join() precede both
                    # paths), and verify_readback runs synchronously on this
                    # thread — so no background reader/writer can still touch
                    # this handle. close() is idempotent (swap-then-close),
                    # so a redundant close on an error path is harmless.
                    dev.close()
                return FlashJobResult(ok=True,
                                      bytes_written=write_result.bytes_written,
                                      source_sha256=write_result.source_sha256)
            except ImagerError as e:
                # Domain error already carries SDState — propagate as-is.
                _log.error("FlashJob FAILED (domain error): %s: %s",
                           type(e).__name__, e, exc_info=True)
                return FlashJobResult(
                    ok=False,
                    bytes_written=write_result.bytes_written if write_result else 0,
                    source_sha256=write_result.source_sha256 if write_result else "",
                    error=e,
                )
            except Exception as e:
                # Audit High #19: bare OSError / RuntimeError from Win32 paths
                # used to escape the FlashJobResult contract and crash the
                # worker thread. Wrap unexpected exceptions in a generic
                # FlashError so callers still get a result.
                #
                # Format manually so the surfaced UI message is English-only
                # — ``{e!r}`` on an OSError expands to the OS-localized
                # ``strerror`` text ("Le système ne peut pas trouver le
                # fichier spécifié" on French Windows etc.). CLAUDE.md
                # forbids French in shipped artefacts. We keep the
                # actionable diagnostics (errno, winerror, filename) and
                # drop the localised prose.
                from astromechos_imager.core.errors import FlashError
                exc_type = type(e).__name__
                if isinstance(e, OSError):
                    parts = [f"errno={e.errno}"]
                    winerr = getattr(e, "winerror", None)
                    if winerr is not None:
                        parts.append(f"winerror={winerr}")
                    if e.filename:
                        parts.append(f"filename={e.filename!r}")
                    detail = f"{exc_type}({', '.join(parts)})"
                else:
                    # Strip embedded newlines / non-ASCII from the message so
                    # the UI dialog stays a single readable line.
                    msg = (str(e) or "<no message>").encode("ascii", "replace").decode("ascii")
                    detail = f"{exc_type}: {msg}"
                wrapped = FlashError(f"unexpected error during flash: {detail}")
                wrapped.__cause__ = e
                # Log the FULL traceback to the session log — without this the
                # only record of a flash failure was the one-line UI message,
                # which made field Errno 5/6 reports impossible to localize.
                _log.error("FlashJob FAILED (unexpected): %s", detail, exc_info=True)
                return FlashJobResult(
                    ok=False,
                    bytes_written=write_result.bytes_written if write_result else 0,
                    source_sha256=write_result.source_sha256 if write_result else "",
                    error=wrapped,
                )
        finally:
            # STICKY LOCK release — this is the ONLY place the held
            # FSCTL_LOCK_VOLUME handles are closed, and it runs strictly
            # LAST: after the inner `finally` closed the raw `dev` handle and
            # after write + verify + customize + deferred-MBR all completed
            # (or after a failure). Closing a locked volume handle releases
            # its lock and lets Windows remount the freshly-written card, so
            # releasing any earlier would let PARTMGR reprotect the partition
            # mid-flash and deny in-partition writes (ERROR_ACCESS_DENIED).
            #
            # Dedupe on the numeric value and drop each handle as we go so a
            # value can never be passed to CloseHandle twice (recycle-safe);
            # close_handle is itself idempotent as belt-and-suspenders.
            seen_handles: set[int] = set()
            while locked_handles:
                h = locked_handles.pop()
                if h in seen_handles:
                    continue
                seen_handles.add(h)
                try:
                    self.platform_io.close_handle(h)
                except Exception:
                    pass  # best-effort; we're already in a finally

    def _sync_cache(self, dev: object) -> None:
        """Best-effort flush of the USB-bridge firmware write cache.

        Calls ``platform_io.sync_cache(handle)`` (SCSI SYNCHRONIZE_CACHE,
        falling back to FlushFileBuffers). No-op when the platform doesn't
        expose it (tests / non-Windows) or the device handle isn't a Win32
        HANDLE. Never raises — cache sync is an optimisation, not a gate.
        """
        sync = getattr(self.platform_io, "sync_cache", None)
        if sync is None:
            return
        handle = getattr(dev, "_h", None)
        if handle is None:
            return
        try:
            sync(handle)
        except Exception:
            pass

    def _run_rootfs_personalization(self, mbr_bytes: bytes, boot: object) -> None:
        """Open the ext4 rootfs partition and apply RootfsPersonalizer.

        Parameters
        ----------
        mbr_bytes:
            First 512 bytes of the disk (already read during customize step).
        boot:
            Already-opened BootPartition object (shared with FirstbootBundle).
        """
        from astromechos_imager.core.rootfs_personalizer import RootfsPersonalizer  # noqa: PLC0415

        debugfs = self.ext4_debugfs_exe
        e2fsck = self.ext4_e2fsck_exe
        # Resolve the e2fsprogs tools when the job didn't carry explicit
        # paths. On Windows that means the BUNDLED debugfs.exe / e2fsck.exe
        # from vendor/ (via the same resolver the rest of the app uses) —
        # NOT the old ``/usr/sbin/debugfs`` WSL/dev fallback, which simply
        # does not exist on a Windows host and crashed the customize step
        # with a raw FileNotFoundError (WinError 2). If the bundled tool is
        # missing, vendored_binaries raises a clear English error naming the
        # expected path — the UID-1000 cold surgery is a hard invariant, so
        # we surface that rather than silently skipping it.
        if debugfs is None or e2fsck is None:
            import sys  # noqa: PLC0415
            if sys.platform == "win32":
                # Default to the BUNDLED tools in vendor/ (NOT the old
                # ``/usr/sbin/debugfs`` WSL fallback, which doesn't exist on
                # Windows and crashed customize with WinError 2). Use the
                # path directly without an existence check so the
                # ``_open_rootfs_partition`` seam stays monkeypatchable in
                # tests; a genuinely missing tool surfaces as a subprocess
                # FileNotFoundError naming the correct vendor path. The UI
                # path (_build_flash_job) resolves these eagerly with a clear
                # pre-write error, so this branch is the test / direct-job
                # fallback.
                from astromechos_imager.core.vendored_binaries import vendor_root  # noqa: PLC0415
                debugfs = debugfs or (vendor_root() / "debugfs.exe")
                e2fsck = e2fsck or (vendor_root() / "e2fsck.exe")
            else:
                # POSIX dev/test host — system e2fsprogs.
                debugfs = debugfs or Path("/usr/sbin/debugfs")
                e2fsck = e2fsck or Path("/usr/sbin/e2fsck")
        rp = _open_rootfs_partition(
            raw_device_path=self.target.device_path,
            mbr_bytes=mbr_bytes,
            debugfs_exe=debugfs,
            e2fsck_exe=e2fsck,
        )
        if rp is None:
            return  # no Linux partition → skip
        try:
            RootfsPersonalizer(self.linux_account, rp, boot).apply()  # type: ignore[arg-type]
        finally:
            rp.close()


@dataclass(frozen=True)
class PairFlashResult:
    master: FlashJobResult
    slave: FlashJobResult


@dataclass
class PairFlashJob:
    platform_io: PlatformIO
    master_image: Path
    master_target: DiskRef
    slave_image: Path
    slave_target: DiskRef
    firstboot_config: FirstbootConfig
    master_pair: Ed25519Pair
    on_progress: Callable[[Role, DiskWriterProgress], None] = field(default=lambda r, p: None)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    parallel: bool = True
    skip_verify: bool = False
    skip_customize: bool = False
    # Phase 5.5.4 / Customize-step restoration: optional cold rootfs
    # surgery. When ``linux_account`` is set, BOTH child FlashJobs run
    # rootfs personalization with the same account — the operator
    # provisions a single UID-1000 identity shared across Master and
    # Slave for SSH key-trust and the runtime side-by-side rsync
    # workflow. Per-role accounts would diverge ``/etc/passwd`` and
    # break the firstboot identity contract.
    linux_account: LinuxAccount | None = None
    ext4_debugfs_exe: Path | None = None
    ext4_e2fsck_exe: Path | None = None

    def _make_job(self, role: Role, image: Path, target: DiskRef) -> FlashJob:
        return FlashJob(
            platform_io=self.platform_io,
            image_path=image, target=target, role=role,
            firstboot_config=self.firstboot_config,
            master_pair=self.master_pair,
            on_progress=lambda p, _r=role: self.on_progress(_r, p),
            cancel_event=self.cancel_event,
            skip_verify=self.skip_verify, skip_customize=self.skip_customize,
            linux_account=self.linux_account,
            ext4_debugfs_exe=self.ext4_debugfs_exe,
            ext4_e2fsck_exe=self.ext4_e2fsck_exe,
        )

    def run(self) -> PairFlashResult:
        m_job = self._make_job(Role.MASTER, self.master_image, self.master_target)
        s_job = self._make_job(Role.SLAVE, self.slave_image, self.slave_target)
        if self.parallel:
            # Audit Medium #32: capture both `result` and exception per
            # thread, so an unexpected exception from either job (e.g.
            # an OSError that slipped through FlashJob.run()'s broad
            # wrapper — should be impossible now but defence in depth)
            # is surfaced via FlashJobResult.error rather than turning
            # into an IndexError on the post-join lookup.
            from astromechos_imager.core.errors import FlashError

            m_box: dict[str, object] = {}
            s_box: dict[str, object] = {}

            def _run_into(box, job):
                try:
                    box["result"] = job.run()
                except BaseException as exc:  # noqa: BLE001
                    box["exc"] = exc

            t1 = threading.Thread(target=_run_into, args=(m_box, m_job),
                                  name="pair-master", daemon=False)
            t2 = threading.Thread(target=_run_into, args=(s_box, s_job),
                                  name="pair-slave", daemon=False)
            t1.start(); t2.start(); t1.join(); t2.join()

            def _unbox(box: dict, role_name: str) -> FlashJobResult:
                if "result" in box:
                    return box["result"]  # type: ignore[return-value]
                exc = box.get("exc")
                wrapped = FlashError(
                    f"unexpected error in {role_name} flash thread: {exc!r}"
                )
                if isinstance(exc, BaseException):
                    wrapped.__cause__ = exc
                return FlashJobResult(
                    ok=False, bytes_written=0, source_sha256="", error=wrapped,
                )

            m = _unbox(m_box, "master")
            s = _unbox(s_box, "slave")
        else:
            m = m_job.run()
            s = s_job.run()
        return PairFlashResult(master=m, slave=s)
