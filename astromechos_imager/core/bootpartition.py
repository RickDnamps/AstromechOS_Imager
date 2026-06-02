"""FAT32 boot partition access (β pyfatfs primary, α drive letter fallback).

Per design spec §5.6.

Two implementation paths:
  β  PyFatFsBootPartition — direct FAT32 access via pyfatfs on the raw image.
     No Windows remount required; works on any file.
  α  DriveLetterBootPartition — writes via the auto-mounted Windows drive letter
     after Windows re-mounts the freshly-written partition.

Auto-fallback orchestrator ``open_boot_partition`` tries β first, then α.
"""
from __future__ import annotations

import logging
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

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

_SECTOR = 512


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


# ── α path: drive letter after Windows remount ─────────────────────────────────

class DriveLetterBootPartition:
    """Writes via the auto-mounted Windows drive letter.

    After ``IOCTL_DISK_UPDATE_PROPERTIES``, Windows auto-mounts a freshly
    written FAT32 partition and assigns it a drive letter.  This adapter
    wraps the mounted volume's root directory.

    This path is only usable on Windows.  It cannot be unit-tested in
    isolation (requires real Windows mount flow), but is exercised by the
    manual E2E test plan.
    """

    def __init__(self, letter: str):
        self._root = Path(f"{letter}:\\")
        if not self._root.exists():
            raise BootPartitionMountError(f"Drive {letter!r}: not mounted")

    # ── BootPartition protocol ──────────────────────────────────────────────

    def write_bytes(self, path: str, data: bytes) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    def read_bytes(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def mkdir(self, path: str) -> None:
        self._resolve(path).mkdir(parents=True, exist_ok=True)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def close(self) -> None:
        pass  # nothing to release; the OS owns the mount

    # ── helpers ────────────────────────────────────────────────────────────

    def _resolve(self, path: str) -> Path:
        """Convert a forward-slash relative path to an absolute Windows path."""
        rel = path.lstrip("/").replace("/", "\\")
        return self._root / rel


# ── Windows drive-letter poller ────────────────────────────────────────────────

def wait_for_new_drive_letter(known_before: set[str], timeout_s: float = 30.0) -> str:
    """Poll ``GetLogicalDrives`` for a letter not in *known_before*.

    Windows-only.  Called after ``IOCTL_DISK_UPDATE_PROPERTIES`` triggers an
    automatic mount of the newly written FAT32 partition.

    :param known_before: Set of drive letters present before the write.
    :param timeout_s: Maximum time to wait before raising.
    :raises BootPartitionMountError: If no new letter appears within *timeout_s*.
    :returns: The first new single-character drive letter (upper-case).
    """
    import ctypes  # noqa: PLC0415

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        bits = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
        present = {chr(ord("A") + i) for i in range(26) if bits & (1 << i)}
        new = present - known_before
        if new:
            return sorted(new)[0]
        time.sleep(0.25)

    raise BootPartitionMountError(
        f"No new drive letter appeared within {timeout_s:.0f} s "
        f"(known before: {sorted(known_before)})"
    )


# ── Auto-fallback orchestrator ─────────────────────────────────────────────────

def open_boot_partition(
    raw_device_path: str,
    layout: BootPartitionLayout,
    known_letters_before: set[str],
    preferred_letter: str | None = None,
) -> "PyFatFsBootPartition | DriveLetterBootPartition":
    """Open the boot partition, preferring the β (pyfatfs) path.

    Algorithm:
    1. If ``preferred_letter`` is provided and that letter is currently
       mounted (the SD already had a drive letter assigned — the common
       case for any card that ever booted), use ``DriveLetterBootPartition``
       directly. This skips the broken "new letter detection" path
       (Bug #2 in the audit: ``FSCTL_DISMOUNT_VOLUME`` doesn't drop the
       letter from ``GetLogicalDrives``, so ``wait_for_new_drive_letter``
       times out after 30 s on already-mounted SDs).
    2. Try ``PyFatFsBootPartition`` (β). On Windows raw devices this
       always fails (Python's ``open()`` can't determine the size of
       ``\\\\.\\PHYSICALDRIVEn``) — the wrapper raises
       ``BootPartitionMountError`` and we fall through.
    3. Fall back to ``DriveLetterBootPartition`` (α) via
       ``wait_for_new_drive_letter`` for fresh unformatted SDs that
       arrive without any pre-existing letter.

    :param raw_device_path: Path to the raw disk image or Win32 device path.
    :param layout: Result of ``find_first_fat32_partition``.
    :param known_letters_before: Drive letters present before the image was
        written (used by the α fallback to detect the newly mounted letter).
    :param preferred_letter: The target's existing drive letter, if known.
        When set and currently mounted, used directly without auto-detect.
    :returns: An object satisfying the ``BootPartition`` protocol.
    :raises BootPartitionMountError: If neither β nor α can mount.
    """
    if preferred_letter and Path(f"{preferred_letter}:\\").exists():
        return DriveLetterBootPartition(preferred_letter)
    try:
        return PyFatFsBootPartition(raw_device_path, layout)
    except BootPartitionMountError:
        # α fallback — only viable on Windows after IOCTL_DISK_UPDATE_PROPERTIES
        letter = wait_for_new_drive_letter(known_letters_before)
        return DriveLetterBootPartition(letter)
