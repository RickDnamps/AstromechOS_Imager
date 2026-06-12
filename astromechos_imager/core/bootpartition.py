"""FAT32 boot partition parsing + β (pyfatfs) access.

Per design spec §5.6.

Production customize writes go through the userspace-FAT writer
(``core/raw_fat_partition.py::RawFatBootPartition``) — this module now only
provides ``find_first_fat32_partition``/``BootPartitionLayout`` (MBR parsing,
shared with the orchestrator) and ``PyFatFsBootPartition`` (β, kept for the
image-fixture round-trip tests). The historical α drive-letter path was
removed (audit WP9, zero production callers).
"""
from __future__ import annotations

import logging
import struct
import sys
from dataclasses import dataclass

from astromechos_imager.core.errors import BootPartitionMountError, BootPartitionWriteError

# ── MBR parsing ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BootPartitionLayout:
    """Location of a FAT32 boot partition within a disk image."""

    offset: int           # bytes from start of disk image
    size: int             # bytes
    partition_type: int   # 0x0B / 0x0C for FAT32, 0x06/0x0E for FAT16


#: Partition types accepted as a FAT32/FAT16 boot partition.
#: Pi OS uses 0x0C (FAT32 LBA); we accept the full family for flexibility.
_FAT_TYPES: frozenset[int] = frozenset({0x0B, 0x0C, 0x06, 0x0E})

from astromechos_imager.core.constants import SECTOR_SIZE as _SECTOR  # noqa: E402


def find_first_fat32_partition(mbr_bytes: bytes) -> BootPartitionLayout:
    """Parse a 512-byte MBR and return the first FAT32/FAT16 partition.

    Pi OS uses MBR (not GPT) and lays out a small FAT32 boot partition first.

    :param mbr_bytes: Exactly 512 bytes from the start of the disk/image.
    :raises BootPartitionMountError: On invalid MBR signature or no FAT entry.
    :returns: ``BootPartitionLayout`` with offset and size in bytes.
    """
    if len(mbr_bytes) < 512 or mbr_bytes[510:512] != b"\x55\xAA":
        raise BootPartitionMountError("Invalid MBR signature")

    for i in range(4):
        base = 446 + i * 16
        entry = mbr_bytes[base : base + 16]
        ptype = entry[4]
        if ptype not in _FAT_TYPES:
            continue
        lba_start: int = struct.unpack_from("<I", entry, 8)[0]
        lba_size: int = struct.unpack_from("<I", entry, 12)[0]
        if lba_size == 0:
            continue  # deleted / empty entry
        return BootPartitionLayout(
            offset=lba_start * _SECTOR,
            size=lba_size * _SECTOR,
            partition_type=ptype,
        )

    raise BootPartitionMountError("No FAT32 partition found in MBR")


# ── pyfatfs import helper ──────────────────────────────────────────────────────

def _import_pyfatfs():
    """Import PyFatFS, stubbing ``pkg_resources`` if needed.

    Python 3.14 ships without ``pkg_resources`` (it was removed from setuptools
    namespace injection in newer releases).  The ``fs`` package (a pyfatfs dep)
    calls ``__import__('pkg_resources').declare_namespace(...)`` at import time;
    this is a no-op we can safely stub.
    """
    if "pkg_resources" not in sys.modules:
        # Provide a minimal stub so fs.__init__ can declare its namespace
        import types
        stub = types.ModuleType("pkg_resources")
        stub.declare_namespace = lambda _name: None  # type: ignore[attr-defined]
        sys.modules["pkg_resources"] = stub
    from pyfatfs.PyFatFS import PyFatFS  # noqa: PLC0415
    return PyFatFS


# ── β path: pyfatfs over raw device ───────────────────────────────────────────

class PyFatFsBootPartition:
    """Direct FAT32 access via pyfatfs (pyfilesystem2 wrapper) on the raw image.

    No Windows drive-letter remount needed.

    API notes vs. the plan:
    - ``PyFatFS.__init__`` takes ``offset`` but NOT ``size`` — the filesystem
      reads from the offset to the end of the file / size of the FAT region.
    - Methods are from the pyfilesystem2 FS base class:
        ``writebytes(path, data)``, ``readbytes(path)``,
        ``makedirs(path, recreate=True)``, ``exists(path)``, ``close()``.
    """

    def __init__(self, raw_device_path: str, layout: BootPartitionLayout):
        PyFatFS = _import_pyfatfs()
        try:
            # offset= places the filesystem start at the partition's LBA offset.
            # pyfatfs 1.1.x does NOT accept a size= parameter.
            self._fs = PyFatFS(filename=raw_device_path, offset=layout.offset)
        except Exception as exc:
            raise BootPartitionMountError(f"pyfatfs mount failed: {exc}") from exc

    # ── BootPartition protocol ──────────────────────────────────────────────

    def write_bytes(self, path: str, data: bytes) -> None:
        try:
            self._fs.writebytes(path, data)
        except Exception as exc:
            raise BootPartitionWriteError(f"write {path!r} failed: {exc}") from exc

    def read_bytes(self, path: str) -> bytes:
        return self._fs.readbytes(path)  # type: ignore[no-any-return]

    def mkdir(self, path: str) -> None:
        try:
            self._fs.makedirs(path, recreate=True)
        except Exception as exc:
            raise BootPartitionWriteError(f"mkdir {path!r} failed: {exc}") from exc

    def exists(self, path: str) -> bool:
        return self._fs.exists(path)  # type: ignore[no-any-return]

    def close(self) -> None:
        """Flush + close the FAT32 filesystem handle.

        Audit Low #45: previously swallowed every exception silently, which
        meant a card with unflushed FAT metadata could be reported as a
        successful flash. We now log the exception (so it surfaces in
        startup.log under frozen builds) but stay non-fatal — the trigger
        marker has already been written and the operator's SD will boot.
        """
        try:
            self._fs.close()
        except Exception as exc:  # noqa: BLE001
            # Non-fatal: the trigger marker has already been written and
            # the operator's SD will boot. Route through standard logging
            # so the warning lands in the JSONL session log AND in
            # startup.log (frozen builds).
            logging.getLogger(__name__).warning(
                "pyfatfs close() raised after trigger write — non-fatal: %s: %s",
                type(exc).__name__,
                exc,
            )


# NOTE (audit WP9): the α path (DriveLetterBootPartition +
# wait_for_new_drive_letter + open_boot_partition) was deleted. It had zero
# production callers — superseded by the userspace-FAT writer
# (core/raw_fat_partition.py::RawFatBootPartition), which never asks Windows
# to mount anything. Only find_first_fat32_partition / BootPartitionLayout /
# PyFatFsBootPartition (test fixtures) remain in use.
