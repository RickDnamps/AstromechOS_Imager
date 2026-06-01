# astromechos_imager/core/orchestrator.py
"""High-level flash orchestration. Per design spec §3, §5, §6.4."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from astromechos_imager.core.bootpartition import (
    BootPartitionLayout,
    find_first_fat32_partition,
    find_rootfs_partition,
    open_boot_partition as _open_boot_partition_impl,
)


def _bootpartition_open(
    raw_device_path: str,
    mbr_bytes: bytes,
    known_letters_before: set[str],
    preferred_letter: str | None = None,
) -> "object | None":
    """Parse the MBR, find the FAT32 partition, and open it.

    Returns None if no FAT32 partition is found (so callers can skip customize).
    This is the single monkeypatching point for tests.

    ``preferred_letter`` (when provided) is forwarded to
    ``open_boot_partition`` so an already-assigned target letter is used
    directly instead of going through the brittle "new letter detection"
    fallback (see Bug #2 in the E2E audit).
    """
    from astromechos_imager.core.errors import BootPartitionMountError  # noqa: PLC0415
    try:
        layout = find_first_fat32_partition(mbr_bytes)
    except BootPartitionMountError:
        return None
    return _open_boot_partition_impl(
        raw_device_path=raw_device_path,
        layout=layout,
        known_letters_before=known_letters_before,
        preferred_letter=preferred_letter,
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
        # Audit High #15: lock_and_dismount returns kernel32 HANDLEs that
        # MUST be closed, otherwise volumes stay locked until process exit
        # and "Flash another" never gets remount + the operator can't see
        # the freshly-written SD in Explorer.
        locked_handles: list[int] = []
        write_result = None
        # Snapshot drive letters AFTER locking the target — the target's
        # own letter is now dismounted, so it falls OUT of the set. After
        # flash + update_disk_properties, the newly auto-mounted partition
        # reappears as the first letter NOT in this set. Without this
        # snapshot, the α fallback (DriveLetterBootPartition) defaulted to
        # the alphabetically-first present letter — typically C: (system
        # drive) — and the AstromechOS customize bundle was silently
        # written to the wrong volume.
        def _snapshot_letters() -> set[str]:
            try:
                import ctypes  # noqa: PLC0415
                bits = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
                return {chr(ord("A") + i) for i in range(26) if bits & (1 << i)}
            except Exception:
                return set()  # non-Windows or test mock
        known_letters_before: set[str] = set()
        try:
            try:
                # 1. Lock + dismount any drive letters for this physical drive.
                locked_handles = list(
                    self.platform_io.lock_and_dismount(self.target.drive_letters) or []
                )
                # Snapshot AFTER dismount — the target's letter is now absent,
                # so when Windows re-mounts the freshly-written FAT32 partition,
                # it will be the first letter NOT in this set.
                known_letters_before = _snapshot_letters()
                # 2. Open raw device + flash.
                dev = self.platform_io.open_raw_device(self.target.physical_drive_id)
                try:
                    with open_image(self.image_path) as src:
                        dw = DiskWriter(src, dev, on_progress=self.on_progress,
                                        cancel_event=self.cancel_event)
                        write_result = dw.run()
                    # 3. Verify — hash-injects the deferred first block so
                    #    the comparison matches the source SHA256 even
                    #    though the MBR region is NOT on disk yet.
                    if not self.skip_verify and not self.cancel_event.is_set():
                        verify_readback(dev,
                                        expected_sha256=write_result.source_sha256,
                                        length=write_result.bytes_written,
                                        on_progress=self.on_progress,
                                        cancel_event=self.cancel_event,
                                        first_block=write_result.first_block_data)
                    # 3.5 Write the deferred first block back to offset 0.
                    # With Mount-Manager letter removed (lock_and_dismount
                    # called DeleteVolumeMountPointW), Windows cannot
                    # auto-mount even after the MBR appears — until step
                    # 4 explicitly re-attaches a letter.
                    if (write_result.first_block_data is not None
                            and not self.cancel_event.is_set()):
                        n = dev.write(0, write_result.first_block_data)
                        if n != len(write_result.first_block_data):
                            from astromechos_imager.core.errors import WriteError  # noqa: PLC0415
                            raise WriteError(
                                f"short write of deferred first block: "
                                f"{n}/{len(write_result.first_block_data)}"
                            )
                        dev.flush()
                    # 4. Rootfs personalization + boot partition customize
                    if not self.skip_customize and not self.cancel_event.is_set():
                        self.platform_io.update_disk_properties(getattr(dev, "_h", 0))
                        # Take the MBR from the deferred-write buffer when
                        # available (no disk round-trip); fall back to a
                        # raw read when the source was too small to defer
                        # a first block.
                        mbr = (write_result.first_block_data[:512]
                               if write_result.first_block_data is not None
                               else dev.read(0, 512))
                        # Re-attach our original drive letter to the freshly
                        # written volume. lock_and_dismount removed the
                        # letter via DeleteVolumeMountPointW so verify could
                        # run without Windows interference; now we put the
                        # letter back so DriveLetterBootPartition can write
                        # the AstromechOS bundle via normal Win32 file I/O.
                        target_letter = (self.target.drive_letters[0]
                                         if self.target.drive_letters else None)
                        if target_letter is not None:
                            attach = getattr(
                                self.platform_io,
                                "attach_letter_to_unmounted_volume",
                                None,
                            )
                            if attach is not None:
                                attach(target_letter, self.target.physical_drive_id)
                        bp = _bootpartition_open(
                            raw_device_path=self.target.device_path,
                            mbr_bytes=mbr,
                            known_letters_before=known_letters_before,
                            preferred_letter=target_letter,
                        )
                        if bp is not None:
                            try:
                                self._assert_bp_targets_our_drive(bp)
                                # 4a. Rootfs personalization (if linux_account provided)
                                if (
                                    self.linux_account is not None
                                    and not self.cancel_event.is_set()
                                ):
                                    self._run_rootfs_personalization(mbr, bp)
                                # 4b. Firstboot bundle (boot partition)
                                if not self.cancel_event.is_set():
                                    FirstbootBundle(self.firstboot_config, self.master_pair).write_to(
                                        bp, self.role)
                            finally:
                                bp.close()
                finally:
                    dev.close()
                return FlashJobResult(ok=True,
                                      bytes_written=write_result.bytes_written,
                                      source_sha256=write_result.source_sha256)
            except ImagerError as e:
                # Domain error already carries SDState — propagate as-is.
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
                from astromechos_imager.core.errors import FlashError
                wrapped = FlashError(f"unexpected error during flash: {e!r}")
                wrapped.__cause__ = e
                return FlashJobResult(
                    ok=False,
                    bytes_written=write_result.bytes_written if write_result else 0,
                    source_sha256=write_result.source_sha256 if write_result else "",
                    error=wrapped,
                )
        finally:
            # Always release the volume locks — failure path included.
            for h in locked_handles:
                try:
                    self.platform_io.close_handle(h)
                except Exception:
                    pass  # best-effort; we're already in a finally

    def _assert_bp_targets_our_drive(self, bp: object) -> None:
        """Hard safety check — refuse to customize unless ``bp`` lives on the target.

        Prevents Bug #1 in the E2E audit (orchestrator silently wrote the
        AstromechOS bundle to ``C:\\`` because the α fallback picked the
        alphabetically-first present drive letter).

        Only applies when ``bp`` is a ``DriveLetterBootPartition`` (the α
        path); the β pyfatfs path writes through the raw device handle
        opened from ``\\\\.\\PHYSICALDRIVEn``, which by construction
        targets our drive.

        Re-enumerates removable drives via ``platform_io`` to discover
        which drive letters currently map to the target's physical drive.
        If ``bp``'s root letter is not in that set — ABORT with
        ``CustomizeTargetMismatchError``. The raw image is already on
        disk, so the SD state is ``BOOTABLE_NO_FIRSTBOOT`` (operator can
        safely re-flash).
        """
        from astromechos_imager.core.bootpartition import DriveLetterBootPartition  # noqa: PLC0415
        from astromechos_imager.core.errors import CustomizeTargetMismatchError  # noqa: PLC0415

        if not isinstance(bp, DriveLetterBootPartition):
            return  # β path — writes via raw device handle, no letter to check
        bp_root = getattr(bp, "_root", None)
        if bp_root is None:
            return
        actual_letter = str(bp_root.drive).rstrip(":\\")
        if not actual_letter:
            raise CustomizeTargetMismatchError(
                "Refusing to customize: boot partition has no resolvable "
                "drive letter — aborting before any write to prevent "
                "spilling AstromechOS bundle files onto an unknown volume."
            )
        # Discover which letters currently map to OUR physical drive.
        target_letters: set[str] = set()
        try:
            drives = list(self.platform_io.enumerate_removable_drives())
        except Exception as exc:  # noqa: BLE001
            raise CustomizeTargetMismatchError(
                f"Refusing to customize: cannot re-enumerate removable "
                f"drives to verify {actual_letter}: maps to the target "
                f"physical drive {self.target.physical_drive_id}: {exc!r}"
            ) from exc
        for d in drives:
            if d.physical_drive_id == self.target.physical_drive_id:
                target_letters.update(d.drive_letters)
        if actual_letter not in target_letters:
            raise CustomizeTargetMismatchError(
                f"SAFETY BLOCK: boot partition resolved to "
                f"'{actual_letter}:' but the target physical drive "
                f"{self.target.physical_drive_id} currently maps to "
                f"{sorted(target_letters) or '(none — drive disconnected?)'}. "
                f"ABORT to prevent writing the AstromechOS bundle to a "
                f"non-target volume (would have leaked to the system drive "
                f"or another removable medium)."
            )

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
        # If exe paths not provided, skip (defensive: shouldn't reach here if
        # linux_account was set without exe paths, but guard for safety)
        if debugfs is None or e2fsck is None:
            rp = _open_rootfs_partition(
                raw_device_path=self.target.device_path,
                mbr_bytes=mbr_bytes,
                debugfs_exe=Path("/usr/sbin/debugfs"),
                e2fsck_exe=Path("/usr/sbin/e2fsck"),
            )
        else:
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
