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

    NOTE: Phase 5.5 rootfs personalization uses a separate parallel symbol;
    this function only handles the boot (FAT32) partition step.
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
from astromechos_imager.core.customization import FirstbootBundle
from astromechos_imager.core.diskwriter import (
    DiskWriter,
    DiskWriterProgress,
    verify_readback,
)
from astromechos_imager.core.errors import ImagerError
from astromechos_imager.core.imagesource import open_image
from astromechos_imager.core.models import DiskRef, Ed25519Pair, FirstbootConfig, Role
from astromechos_imager.core.platform_io import PlatformIO


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

    def run(self) -> FlashJobResult:
        try:
            # 1. Lock + dismount any drive letters for this physical drive
            self.platform_io.lock_and_dismount(self.target.drive_letters)
            # 2. Open raw device + flash
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
                # 4. Customize via boot partition
                # NOTE: Phase 5.5 rootfs personalization will be inserted here
                # (between verify and customize) once Task 5.5.4 lands.
                if not self.skip_customize:
                    self.platform_io.update_disk_properties(getattr(dev, "_h", 0))
                    mbr = dev.read(0, 512)
                    bp = _bootpartition_open(
                        raw_device_path=self.target.device_path,
                        mbr_bytes=mbr,
                        known_letters_before=set(),
                    )
                    if bp is not None:
                        try:
                            FirstbootBundle(self.firstboot_config, self.master_pair).write_to(
                                bp, self.role)
                        finally:
                            bp.close()
            finally:
                dev.close()
            return FlashJobResult(ok=True, bytes_written=write_result.bytes_written,
                                   source_sha256=write_result.source_sha256)
        except ImagerError as e:
            return FlashJobResult(ok=False, bytes_written=0, source_sha256="", error=e)


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
            m_result: list[FlashJobResult] = []
            s_result: list[FlashJobResult] = []
            t1 = threading.Thread(target=lambda: m_result.append(m_job.run()))
            t2 = threading.Thread(target=lambda: s_result.append(s_job.run()))
            t1.start(); t2.start(); t1.join(); t2.join()
            m, s = m_result[0], s_result[0]
        else:
            m = m_job.run()
            s = s_job.run()
        return PairFlashResult(master=m, slave=s)
