# astromechos_imager/core/orchestrator.py
"""High-level flash orchestration. Per design spec §3, §5, §6.4."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from astromechos_imager.core.bootpartition import find_first_fat32_partition


def _bootpartition_open(
    platform_io: PlatformIO,
    physical_drive_id: int,
    mbr_bytes: bytes,
) -> object | None:
    """Find the FAT32 partition in the MBR and open it via userspace FAT.

    Returns None if no FAT32 partition is found. The returned
    ``RawFatBootPartition`` reads/writes the FAT in userspace (pyfatfs over the
    raw device), so Windows never mounts the partition — no drive letter, no
    "Format?" pop-up. Single monkeypatching point for tests.
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
    # Optional first-boot account setup. When None, only the FAT firstboot
    # bundle is written (no /firstrun.sh).
    linux_account: LinuxAccount | None = None

    def run(self) -> FlashJobResult:
        # Suppress this worker thread's shell error dialogs (no-op without the
        # native DLL) so raw device I/O can't trigger an Explorer pop-up.
        try:
            from astromechos_imager.platform import native_shell_quiet
            if native_shell_quiet.available():
                native_shell_quiet.quiet_thread()
        except Exception:
            pass
        write_result = None
        dev = None
        # True once the card carries a valid partition table again (deferred MBR
        # written). If it stays False after open_raw_device wiped the layout the
        # card is RAW, and the outer finally restores a clean exFAT volume.
        mbr_written = False
        # Disable Windows automount for the WHOLE Imager session. The "Format
        # this disk?" pop-up fires when Windows auto-mounts a freshly-INSERTED
        # card mid-session and probes its (being-overwritten) filesystem — the
        # SLAVE is the classic victim, inserted while warm right after the
        # Master. This is deliberately NOT re-enabled per-card: re-enabling
        # between Master and Slave let Windows grab + probe the Slave at
        # insertion and pop the dialog at ~5% of the write. Automount is
        # restored ONLY when the app closes (app.aboutToQuit → enable_automount)
        # or, after a crash, on the next launch via
        # restore_automount_if_crashed() + the marker file. Idempotent across
        # cards (mountvol /N again is a harmless no-op). Best-effort.
        try:
            disable = getattr(self.platform_io, "disable_automount", None)
            if disable is not None and not disable():
                _log.warning(
                    "automount could NOT be disabled (elevation?) — the "
                    "mid-flash pop-up defense now relies on the deferred "
                    "MBR alone"
                )
        except Exception:
            pass
        try:
            try:
                # Preflight validates everything that can fail before any
                # destructive device mutation; a PreflightError aborts with the
                # card untouched.
                _log.info("PHASE preflight: validating before any device mutation")
                self._preflight()
                _log.info("PHASE preflight: PASSED — beginning flash")
                # 1. Dismount every volume on this drive and drop its drive
                #    letter before opening the physical device. The baseline
                #    recipe locks/unlocks/closes per volume internally and
                #    returns [] — no handle survives the call.
                self.platform_io.lock_and_dismount(
                    self.target.drive_letters,
                    self.target.physical_drive_id,
                )
                # 1b. ACTIVE-WAIT GATE: never open \\.\PhysicalDrive while
                #     Windows still has a drive letter on the target. The Master
                #     flashes clean because the OS has released the card by then;
                #     the freshly-inserted Slave is still held by Explorer
                #     (AutoPlay) and re-bound to K:, and writing under it pops
                #     "Format this disk?". Re-dismount + poll until released.
                self._wait_for_unmount()
                # 2. Open one raw device handle for write, verify, and the final
                #    MBR write. open_raw_device wipes the in-memory partition
                #    layout so PARTMGR stops policing in-partition writes.
                dev = self.platform_io.open_raw_device(self.target.physical_drive_id)
                _log.info("FlashJob START role=%s phys_id=%s image=%s skip_verify=%s "
                          "skip_customize=%s linux_account=%s",
                          getattr(self.role, "value", self.role),
                          self.target.physical_drive_id, self.image_path.name,
                          self.skip_verify, self.skip_customize,
                          "set" if self.linux_account else "none")
                # NOTE: do NOT pre-zero sector 0 here. Empirically (field log
                # 2026-06-10, master vs slave) wiping the partition table up
                # front turns the card RAW for the whole write window, and a RAW
                # card with a still-attached drive letter is EXACTLY what makes
                # the shell pop "Format this disk?". On the master the same
                # pre-zero was denied (ERROR_ACCESS_DENIED) so the card never
                # went RAW — and it flashed completely silently. The silent path
                # is therefore: leave sector 0 alone, let the streaming write +
                # deferred-MBR-last carry the partition table, and rely on
                # lock_and_dismount + IOCTL_DISK_DELETE_DRIVE_LAYOUT + automount
                # disable + native shell-quiet to keep the shell out of it.
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

                    # 4. Userspace-FAT customize, while the deferred MBR is still
                    #    absent so Windows can't auto-mount the FAT partition
                    #    (no drive letter, no "Format?" pop-up).
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
                                # cloud-init NoCloud, the official rpi-imager
                                # Trixie way: drop user-data + meta-data on the
                                # FAT and rewrite cmdline.txt with the `resize`
                                # token (native partition grow) +
                                # ds=nocloud;i=<unique> (activates cloud-init and
                                # forces a per-flash re-provision). NO init= (dead
                                # PID-1 hack), NO firstrun.sh. Golden untouched.
                                if not self.cancel_event.is_set():
                                    self._write_cloud_init(bp)
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
                        mbr_written = True   # card now has a valid layout
                    elif (write_result.first_block_data is None
                            and not self.cancel_event.is_set()):
                        # Degenerate path (image < 1 MB, no deferred block):
                        # the streaming write already wrote sector 0, so the
                        # card carries the image's own MBR — it's valid.
                        mbr_written = True
                finally:
                    # DiskWriter joins its threads and verify runs synchronously
                    # before this point, so no background I/O can touch the
                    # handle. close() is idempotent.
                    dev.close()
                # Eject on success, on a FRESH handle (ours is now closed so it
                # can't pin the device). Windows drops the freshly-written
                # volumes instead of prompting "Format?" for the unreadable ext4
                # rootfs. Best-effort — never affects the result.
                if mbr_written and not self.cancel_event.is_set():
                    finalize = getattr(self.platform_io, "finalize_eject", None)
                    ejected = False
                    if finalize is not None:
                        try:
                            ejected = bool(
                                finalize(self.target.physical_drive_id))
                        except Exception:
                            ejected = False
                    if not ejected:
                        # Most SD-USB bridges reject IOCTL_STORAGE_EJECT_MEDIA.
                        # Without a letter re-attach the flashed card stays
                        # present but LETTERLESS — invisible in Explorer until
                        # physical reinsertion (the "captive reader", audit
                        # defect F1). Give the fresh FAT32 boot volume a letter
                        # so the operator sees a healthy card. Best-effort.
                        visible = getattr(
                            self.platform_io, "make_card_visible", None)
                        if visible is not None:
                            try:
                                visible(self.target.physical_drive_id)
                            except Exception:
                                pass
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
            # Cleanup. The real work is closing the raw device handle, which
            # also covers the path where open_raw_device or lock_and_dismount
            # raised before the inner try/finally that normally closes dev.
            # _Win32RawDevice.close is idempotent, so a redundant close after
            # the inner-finally close is harmless. (The old locked_handles
            # close loop is gone: lock_and_dismount releases its locks
            # internally and always returns [] — the loop was a permanent
            # no-op kept for a Protocol shape nothing implements.)
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass

            # Card recovery: if the device was opened (layout wiped) but no
            # valid MBR was written back (cancel or mid-flash failure), the card
            # is RAW. Quick-format it to a clean exFAT volume so the operator
            # sees a usable drive. Best-effort, after the handle is closed.
            if dev is not None and not mbr_written:
                restore = getattr(self.platform_io, "restore_readable_exfat", None)
                if restore is not None:
                    try:
                        self.on_progress(DiskWriterProgress(
                            phase="restoring_card", bytes_done=0,
                            bytes_total=0, throughput_bps=0.0,
                        ))
                        _log.info("flash incomplete (cancel/failure) — "
                                  "restoring target to clean exFAT")
                        restore(self.target.physical_drive_id)
                    except Exception:
                        pass  # best-effort recovery; never mask the real result

            # NOTE: automount is intentionally NOT re-enabled here. It stays
            # disabled for the whole session (across BOTH cards) so Windows
            # can't grab + probe the freshly-inserted Slave and pop "Format
            # this disk?". The single restore point is app shutdown
            # (app.aboutToQuit → enable_automount); a crash is covered by the
            # marker file + restore_automount_if_crashed() on next launch.

    def _wait_for_unmount(self, timeout_s: float = 30.0, poll_s: float = 0.25) -> None:
        r"""Active-wait gate: keep force-dismounting until the target disk is
        letter-less, so we never open ``\\.\PhysicalDrive`` while Windows still
        has the card mounted.

        The Master flashes clean because by flash time Windows has released the
        card; the freshly-inserted Slave is still held by Explorer (AutoPlay)
        and re-bound to its remembered letter (K:), and writing under it pops
        "Format this disk?". This reproduces the Master's released state for the
        Slave — re-dismount + poll until no letter is associated. Device-safe
        (FSCTL dismount + DeleteVolumeMountPoint only, via the platform hooks);
        on timeout it proceeds best-effort, i.e. exactly the prior behaviour, so
        it can never regress a flash. No-op on platforms/fakes lacking the hooks.
        """
        import time as _t  # noqa: PLC0415
        letters_fn = getattr(self.platform_io, "letters_on_disk", None)
        force_fn = getattr(self.platform_io, "force_unmount_letter", None)
        if letters_fn is None or force_fn is None:
            return
        deadline = _t.monotonic() + timeout_s
        announced = False
        while True:
            try:
                letters = list(letters_fn(self.target.physical_drive_id) or [])
            except Exception:  # noqa: BLE001
                return  # can't probe — don't block the flash
            if not letters:
                if announced:
                    _log.info("PHASE wait-unmount: target disk released by Windows")
                return
            for letter in letters:
                try:
                    force_fn(letter)
                except Exception:  # noqa: BLE001
                    pass
            if _t.monotonic() >= deadline:
                _log.info(
                    "PHASE wait-unmount: disk %s still holds %s after %.0fs — "
                    "proceeding best-effort (pop-up possible, write unaffected)",
                    self.target.physical_drive_id, letters, timeout_s,
                )
                return
            if not announced:
                _log.info("PHASE wait-unmount: waiting for Windows to release %s "
                          "on disk %s", letters, self.target.physical_drive_id)
                announced = True
            self.on_progress(DiskWriterProgress(
                phase="waiting_unmount", bytes_done=0, bytes_total=0,
                throughput_bps=0.0,
            ))
            _t.sleep(poll_s)

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

    def _preflight(self) -> None:
        """Validate everything that can fail before any destructive device
        mutation, so a problem aborts with the card untouched (PreflightError,
        sd_state="SAFE"). Account setup is FAT firstrun.sh, so the only check
        is that the source image exists.
        """
        from astromechos_imager.core.errors import DriveNotFoundError  # noqa: PLC0415
        if not self.image_path.is_file():
            raise DriveNotFoundError(f"image file not found: {self.image_path}")

    def _write_cloud_init(self, boot: object) -> None:
        """Provision the OS via cloud-init NoCloud (official rpi-imager flow).

        Writes ``meta-data`` (unique per-flash instance-id) and ``user-data``
        (account + password as a #cloud-config, when an account is set) to the
        FAT boot partition, then rewrites ``cmdline.txt`` with the ``resize``
        token + ``ds=nocloud;i=<instance_id>``. The Golden Image is never
        modified; cloud-init applies everything on first boot.
        """
        import time as _time  # noqa: PLC0415

        from astromechos_imager.core.cloud_init_generator import (  # noqa: PLC0415
            EMPTY_USER_DATA,
            build_cmdline,
            generate_instance_id,
            generate_meta_data,
            generate_user_data,
        )

        instance_id = generate_instance_id(int(_time.time() * 1000))
        boot.write_bytes("/meta-data", generate_meta_data(instance_id))  # type: ignore[attr-defined]
        acc = self.linux_account
        if acc is not None:
            boot.write_bytes(  # type: ignore[attr-defined]
                "/user-data",
                generate_user_data(acc.username, acc.crypt_sha512, role=self.role),
            )
            _log.info(
                "PHASE customize: cloud-init user-data written (user=%s, role=%s)",
                acc.username,
                getattr(self.role, "value", self.role),
            )
        else:
            # Still a valid NoCloud seed so cloud-init runs and grows the rootfs.
            boot.write_bytes("/user-data", EMPTY_USER_DATA)  # type: ignore[attr-defined]
            _log.info("PHASE customize: cloud-init user-data written (no account)")

        cmdline = boot.read_bytes("/cmdline.txt")  # type: ignore[attr-defined]
        new_cmdline = build_cmdline(cmdline, instance_id)
        if new_cmdline != cmdline:
            boot.write_bytes("/cmdline.txt", new_cmdline)  # type: ignore[attr-defined]
        _log.info(
            "PHASE customize: cmdline rewired — resize token + ds=nocloud;i=%s",
            instance_id,
        )


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
    # When set, BOTH child FlashJobs use the same account — a single UID-1000
    # identity shared across Master and Slave for SSH key-trust.
    linux_account: LinuxAccount | None = None

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
        )

    def run(self) -> PairFlashResult:
        m_job = self._make_job(Role.MASTER, self.master_image, self.master_target)
        s_job = self._make_job(Role.SLAVE, self.slave_image, self.slave_target)
        if self.parallel:
            # Capture each thread's result or exception so a failure surfaces
            # via FlashJobResult.error instead of an IndexError after join.
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
