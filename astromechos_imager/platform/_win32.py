"""Win32 constants and ctypes prototypes. Isolated so unit tests can pin
the values without pulling in kernel32 at import time on non-Windows CI."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

# CreateFileW access + share + create-disposition
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_FLAG_WRITE_THROUGH = 0x80000000
INVALID_HANDLE_VALUE = -1

# Volume control
FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_DISMOUNT_VOLUME = 0x00090020
FSCTL_ALLOW_EXTENDED_DASD_IO = 0x00090083

# Disk IOCTL
IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808


class DISK_GEOMETRY_EX(ctypes.Structure):
    _fields_ = [
        ("Cylinders", ctypes.c_longlong),
        ("MediaType", wintypes.DWORD),
        ("TracksPerCylinder", wintypes.DWORD),
        ("SectorsPerTrack", wintypes.DWORD),
        ("BytesPerSector", wintypes.DWORD),
        ("DiskSize", ctypes.c_longlong),
        ("Data", ctypes.c_byte * 32),
    ]


# Lazily load kernel32 — never at import time so non-Windows CI can still import.
_kernel32 = None


def kernel32():
    global _kernel32
    if _kernel32 is None:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        _kernel32.CreateFileW.restype = wintypes.HANDLE
        _kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        _kernel32.DeviceIoControl.restype = wintypes.BOOL
        _kernel32.WriteFile.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        _kernel32.WriteFile.restype = wintypes.BOOL
        _kernel32.ReadFile.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        _kernel32.ReadFile.restype = wintypes.BOOL
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32.CloseHandle.restype = wintypes.BOOL
        _kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        _kernel32.FlushFileBuffers.restype = wintypes.BOOL
        _kernel32.SetFilePointerEx.argtypes = [
            wintypes.HANDLE, ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD,
        ]
        _kernel32.SetFilePointerEx.restype = wintypes.BOOL
    return _kernel32
