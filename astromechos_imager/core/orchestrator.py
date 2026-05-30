# astromechos_imager/core/orchestrator.py
"""High-level flash orchestration. Per design spec §3, §5, §6.4."""
from __future__ import annotations

import threading
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
) -> "object | None":
    """Parse the MBR, find the FAT32 partition, and open it.

    Returns None if no FAT32 partition is found (so callers can skip customize).
    This is the single monkeypatching point for tests.
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
        try:
            try:
                # 1. Lock + dismount any drive letters for this physical drive.
                locked_handles = list(
                    self.platform_io.lock_and_dismount(self.target.drive_letters) or []
                )
                # 2. Open raw device + flash.
                dev = self.platform_io.open_raw_device(self.target.physical_drive_id)
                try:
                    with open_image(self.image_path) as src:
                        dw = DiskWriter(src, dev, on_progress=self.on_progress,
                                        cancel_event=self.cancel_event)
                        write_result = dw.run()
                    # 3. Verify
                    if not self.skip_verify and not self.cancel_event.is_set():
                        verify_readback(dev,
                                        expected_sha256=write_result.source_sha256,
                                        length=write_result.bytes_written,
                                        on_progress=self.on_progress,
                                        cancel_event=self.cancel_event)
                    # 4. Rootfs personalization + boot partition customize
                    if not self.skip_customize and not self.cancel_event.is_set():
                        self.platform_io.update_disk_properties(getattr(dev, "_h", 0))
                        mbr = dev.read(0, 512)
                        bp = _bootpartition_open(
                            raw_device_path=self.target.device_path,
                            mbr_bytes=mbr,
                            known_letters_before=set(),
                        )
                        if bp is not None:
                            try:
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

    def _make_job(self, role: Role, image: Path, target: DiskRef) -> FlashJob:
        return FlashJob(
            platform_io=self.platform_io,
            image_path=image, target=target, role=role,
            firstboot_config=self.firstboot_config,
            master_pair=self.master_pair,
            on_progress=lambda p, _r=role: self.on_progress(_r, p),
            cancel_event=self.cancel_event,
            skip_verify=self.skip_verify, skip_customize=self.skip_customize,
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
