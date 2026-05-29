"""Windows platform IO. Per design spec §5.1-5.2.

ONLY this module imports Win32 APIs. Everything else routes through
core/platform_io.py Protocols.
"""
from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes
from typing import Iterator

from astromechos_imager.core.models import DiskRef

_MAX_SD_BYTES = 256 * 1024 * 1024 * 1024   # hard cap — no R2 build needs > 256 GB
_PHYS_DRIVE_RE = re.compile(r"PHYSICALDRIVE(\d+)", re.IGNORECASE)


def _wmi_query() -> list:
    """Query Win32_DiskDrive via WMI. Indirected for monkeypatching in tests."""
    import win32com.client  # pywin32
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    q = ("SELECT DeviceID, Size, Model, SerialNumber, InterfaceType, MediaType "
         "FROM Win32_DiskDrive")
    return list(wmi.ExecQuery(q))


def _drive_letters_for(device_id: str) -> tuple[str, ...]:
    """Resolve drive letters mounted on a Win32_DiskDrive via the partition graph."""
    import win32com.client
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    letters: list[str] = []
    parts = wmi.ExecQuery(
        f"ASSOCIATORS OF {{Win32_DiskDrive.DeviceID='{device_id}'}} "
        "WHERE AssocClass=Win32_DiskDriveToDiskPartition"
    )
    for part in parts:
        logicals = wmi.ExecQuery(
            f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{part.DeviceID}'}} "
            "WHERE AssocClass=Win32_LogicalDiskToPartition"
        )
        for logical in logicals:
            if logical.DeviceID:
                letters.append(logical.DeviceID.rstrip(":"))
    return tuple(letters)


def _system_drive_id() -> int:
    """Return the PhysicalDriveN number that hosts %SystemDrive% (e.g. C:)."""
    sys_letter = os.environ.get("SystemDrive", "C:").rstrip(":")
    import win32com.client
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    for ld in wmi.ExecQuery(f"SELECT * FROM Win32_LogicalDisk WHERE DeviceID='{sys_letter}:'"):
        parts = wmi.ExecQuery(
            f"ASSOCIATORS OF {{Win32_LogicalDisk.DeviceID='{ld.DeviceID}'}} "
            "WHERE AssocClass=Win32_LogicalDiskToPartition"
        )
        for part in parts:
            drives = wmi.ExecQuery(
                f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{part.DeviceID}'}} "
                "WHERE AssocClass=Win32_DiskDriveToDiskPartition"
            )
            for drive in drives:
                m = _PHYS_DRIVE_RE.search(drive.DeviceID)
                if m:
                    return int(m.group(1))
    return -1


def enumerate_removable_drives() -> Iterator[DiskRef]:
    """Yield only safe removable candidates. Refs design spec §5.1."""
    sys_id = _system_drive_id()
    for d in _wmi_query():
        is_usb = (d.InterfaceType or "").upper() == "USB"
        is_removable = "removable" in (d.MediaType or "").lower()
        if not (is_usb or is_removable):
            continue
        m = _PHYS_DRIVE_RE.search(d.DeviceID or "")
        if not m:
            continue
        phys_id = int(m.group(1))
        if phys_id == sys_id:
            continue
        size = int(d.Size or 0)
        if size <= 0 or size > _MAX_SD_BYTES:
            continue
        yield DiskRef(
            physical_drive_id=phys_id,
            device_path=d.DeviceID,
            drive_letters=_drive_letters_for(d.DeviceID),
            size_bytes=size,
            model=(d.Model or "Unknown").strip(),
            serial=(d.SerialNumber or "").strip(),
        )


# ── Lock / dismount / raw device open ─────────────────────────────────────

from astromechos_imager.core.errors import DriveLockError, DrivePermissionError
from astromechos_imager.platform._win32 import (
    GENERIC_READ, GENERIC_WRITE, FILE_SHARE_READ, FILE_SHARE_WRITE,
    OPEN_EXISTING, FILE_FLAG_NO_BUFFERING, FILE_FLAG_WRITE_THROUGH,
    FSCTL_LOCK_VOLUME, FSCTL_DISMOUNT_VOLUME, INVALID_HANDLE_VALUE,
    IOCTL_DISK_UPDATE_PROPERTIES, IOCTL_STORAGE_EJECT_MEDIA,
    DISK_GEOMETRY_EX, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, kernel32,
)


def _ctl(handle: int, code: int, in_buf: bytes = b"") -> None:
    k = kernel32()
    out = wintypes.DWORD(0)
    ok = k.DeviceIoControl(
        handle, code,
        ctypes.c_char_p(in_buf) if in_buf else None, len(in_buf),
        None, 0, ctypes.byref(out), None,
    )
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"DeviceIoControl(0x{code:08X}) failed (Win32 err {err})")


def _create_volume_handle(letter: str) -> int:
    r"""Open \\.\X: for FSCTL operations. Returns handle or raises."""
    k = kernel32()
    path = f"\\\\.\\{letter}:"
    h = k.CreateFileW(
        path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING, 0, None,
    )
    if h == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        if err == 5:  # ERROR_ACCESS_DENIED
            raise DrivePermissionError(f"Cannot open volume {letter}: (need admin?)")
        raise OSError(err, f"CreateFileW({path}) failed")
    return h


def lock_and_dismount(letters: tuple[str, ...]) -> list[int]:
    """For each drive letter, lock + dismount and keep the handle open.
    Returns the list of handles — caller closes them after raw write completes.
    Refs design spec §5.2 — retries 3× at 500 ms."""
    handles: list[int] = []
    for letter in letters:
        h = _create_volume_handle(letter)
        last_err = None
        for attempt in range(3):
            try:
                _ctl(h, FSCTL_LOCK_VOLUME)
                break
            except OSError as e:
                last_err = e
                time.sleep(0.5)
        else:
            kernel32().CloseHandle(h)
            for prev in handles:
                kernel32().CloseHandle(prev)
            raise DriveLockError(
                f"FSCTL_LOCK_VOLUME failed for {letter}: after 3 retries "
                f"(close Explorer / antivirus). Last err: {last_err}"
            )
        _ctl(h, FSCTL_DISMOUNT_VOLUME)
        handles.append(h)
    return handles


def open_raw_device(physical_drive_id: int) -> int:
    r"""Open \\.\PHYSICALDRIVEn for raw read+write. Returns handle or raises."""
    k = kernel32()
    path = f"\\\\.\\PHYSICALDRIVE{physical_drive_id}"
    h = k.CreateFileW(
        path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING, FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH, None,
    )
    if h == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateFileW({path}) failed")
    return h


def close_handle(h: int) -> None:
    kernel32().CloseHandle(h)


def update_disk_properties(h: int) -> None:
    """After writing partition table, force Windows to re-enumerate volumes."""
    _ctl(h, IOCTL_DISK_UPDATE_PROPERTIES)


def eject_media(h: int) -> None:
    """Best-effort eject. Caller logs warning on failure."""
    _ctl(h, IOCTL_STORAGE_EJECT_MEDIA)


# ── _Win32RawDevice + helpers ──────────────────────────────────────────────

from astromechos_imager.core.platform_io import RawDevice  # noqa: E402 (Protocol, no runtime dep)


class _Win32RawDevice:
    """RawDevice adapter wrapping a kernel32 HANDLE.

    The sector_size is queried lazily on first write/read so unit tests that
    only construct the object don't pay the syscall.
    """

    def __init__(self, handle: int, size_bytes: int):
        self._h = handle
        self.size_bytes = size_bytes
        self._sector_size: int | None = None

    @property
    def sector_size(self) -> int:
        if self._sector_size is None:
            self._sector_size = _query_sector_size(self._h)
        return self._sector_size

    def write(self, offset: int, data: bytes) -> int:
        _seek(self._h, offset)
        written = wintypes.DWORD(0)
        ok = kernel32().WriteFile(
            self._h, ctypes.c_char_p(data), len(data),
            ctypes.byref(written), None,
        )
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(err, f"WriteFile failed at offset {offset}")
        return written.value

    def read(self, offset: int, length: int) -> bytes:
        _seek(self._h, offset)
        buf = ctypes.create_string_buffer(length)
        got = wintypes.DWORD(0)
        ok = kernel32().ReadFile(self._h, buf, length, ctypes.byref(got), None)
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(err, f"ReadFile failed at offset {offset}")
        return bytes(buf.raw[: got.value])

    def flush(self) -> None:
        kernel32().FlushFileBuffers(self._h)

    def close(self) -> None:
        close_handle(self._h)


def _seek(h: int, offset: int) -> None:
    new_pos = ctypes.c_longlong(0)
    ok = kernel32().SetFilePointerEx(h, offset, ctypes.byref(new_pos), 0)  # FILE_BEGIN
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"SetFilePointerEx({offset}) failed")


def _query_sector_size(h: int) -> int:
    out = DISK_GEOMETRY_EX()
    written = wintypes.DWORD(0)
    ok = kernel32().DeviceIoControl(
        h, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, None, 0,
        ctypes.byref(out), ctypes.sizeof(out),
        ctypes.byref(written), None,
    )
    if not ok:
        return 512  # safe default
    return int(out.BytesPerSector)


# ── WindowsPlatformIO facade ───────────────────────────────────────────────

class WindowsPlatformIO:
    def enumerate_removable_drives(self):
        return list(enumerate_removable_drives())

    def lock_and_dismount(self, letters):
        return lock_and_dismount(letters)

    def open_raw_device(self, physical_drive_id):
        h = open_raw_device(physical_drive_id)
        # Re-query size from WMI to avoid a second sector_size syscall during write loop
        size = 0
        for d in enumerate_removable_drives():
            if d.physical_drive_id == physical_drive_id:
                size = d.size_bytes
                break
        return _Win32RawDevice(h, size)

    def close_handle(self, handle):
        close_handle(handle)

    def update_disk_properties(self, handle):
        update_disk_properties(handle)

    def eject_media(self, handle):
        eject_media(handle)
