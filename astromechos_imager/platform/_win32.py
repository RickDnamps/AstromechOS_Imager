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
FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
# CreateFileW / FindFirstVolumeW etc. have restype = wintypes.HANDLE
# (a c_void_p). On FAILURE the Win32 API returns (HANDLE)-1, which ctypes
# surfaces as the UNSIGNED pointer value — 0xFFFFFFFFFFFFFFFF on 64-bit,
# 0xFFFFFFFF on 32-bit — NOT Python's signed -1. Comparing against a bare
# -1 therefore SILENTLY MISSED every failed open: the bogus handle slipped
# through and the first SetFilePointerEx/WriteFile on it returned
# ERROR_INVALID_HANDLE (errno 6). Derive the sentinel from ctypes so the
# `h == INVALID_HANDLE_VALUE` checks actually fire.
import ctypes as _ctypes  # noqa: E402

INVALID_HANDLE_VALUE = _ctypes.c_void_p(-1).value  # 0xFFFFFFFFFFFFFFFF on win64

# Volume control
FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_UNLOCK_VOLUME = 0x0009001C
FSCTL_DISMOUNT_VOLUME = 0x00090020
FSCTL_ALLOW_EXTENDED_DASD_IO = 0x00090083

# Disk IOCTL
IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
IOCTL_DISK_DELETE_DRIVE_LAYOUT = 0x0007C100
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000
# SCSI pass-through (SYNCHRONIZE_CACHE to flush USB-bridge firmware cache).
IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x0004D014
SCSI_IOCTL_DATA_UNSPECIFIED = 2
SCSIOP_SYNCHRONIZE_CACHE = 0x35


class SCSI_PASS_THROUGH_DIRECT(ctypes.Structure):
    """winioctl SCSI_PASS_THROUGH_DIRECT + an inline 32-byte sense buffer."""
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("ScsiStatus", ctypes.c_ubyte),
        ("PathId", ctypes.c_ubyte),
        ("TargetId", ctypes.c_ubyte),
        ("Lun", ctypes.c_ubyte),
        ("CdbLength", ctypes.c_ubyte),
        ("SenseInfoLength", ctypes.c_ubyte),
        ("DataIn", ctypes.c_ubyte),
        ("DataTransferLength", wintypes.ULONG),
        ("TimeOutValue", wintypes.ULONG),
        ("DataBuffer", ctypes.c_void_p),
        ("SenseInfoOffset", wintypes.ULONG),
        ("Cdb", ctypes.c_ubyte * 16),
    ]


class SCSI_PASS_THROUGH_DIRECT_WITH_SENSE(ctypes.Structure):
    _fields_ = [
        ("sptd", SCSI_PASS_THROUGH_DIRECT),
        ("Filler", wintypes.ULONG),
        ("Sense", ctypes.c_ubyte * 32),
    ]


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
        # Mount Manager APIs: after lock+dismount+unlock+close, call
        # DeleteVolumeMountPointW to drop the drive letter from Mount Manager
        # state. Without this, Windows re-discovers the freshly-written
        # partition table and auto-mounts via the OLD letter assignment,
        # racing with verify readback and corrupting hashes.
        _kernel32.DeleteVolumeMountPointW.argtypes = [wintypes.LPCWSTR]
        _kernel32.DeleteVolumeMountPointW.restype = wintypes.BOOL
        # Listing volumes (used to discover the new volume GUID Windows
        # assigns to the freshly-written partition, so we can re-attach
        # our original drive letter for the customize step).
        _kernel32.FindFirstVolumeW.argtypes = [
            wintypes.LPWSTR, wintypes.DWORD,
        ]
        _kernel32.FindFirstVolumeW.restype = wintypes.HANDLE
        _kernel32.FindNextVolumeW.argtypes = [
            wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
        ]
        _kernel32.FindNextVolumeW.restype = wintypes.BOOL
        _kernel32.FindVolumeClose.argtypes = [wintypes.HANDLE]
        _kernel32.FindVolumeClose.restype = wintypes.BOOL
        _kernel32.SetVolumeMountPointW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR,
        ]
        _kernel32.SetVolumeMountPointW.restype = wintypes.BOOL
        _kernel32.GetVolumePathNamesForVolumeNameW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ]
        _kernel32.GetVolumePathNamesForVolumeNameW.restype = wintypes.BOOL
        # GetVolumeInformationW — query whether a volume actually has a
        # recognised filesystem. Used as a readiness probe before
        # attaching the operator's drive letter: a stale Mount Manager
        # entry surviving an IOCTL_DISK_DELETE_DRIVE_LAYOUT would otherwise
        # be picked up first, attaching K: to a phantom volume Windows
        # then refuses to read ("Le volume ne contient pas de système
        # de fichiers connu" pop-up).
        _kernel32.GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR,            # lpRootPathName ("X:\")
            wintypes.LPWSTR,             # lpVolumeNameBuffer
            wintypes.DWORD,              # nVolumeNameSize
            ctypes.POINTER(wintypes.DWORD),  # lpVolumeSerialNumber
            ctypes.POINTER(wintypes.DWORD),  # lpMaximumComponentLength
            ctypes.POINTER(wintypes.DWORD),  # lpFileSystemFlags
            wintypes.LPWSTR,             # lpFileSystemNameBuffer
            wintypes.DWORD,              # nFileSystemNameSize
        ]
        _kernel32.GetVolumeInformationW.restype = wintypes.BOOL
        # SetErrorMode lets the process tell Windows NOT to surface its
        # own "Format X:?" / "X: is not accessible" message boxes when
        # opening a freshly-written removable device. We OR
        # SEM_FAILCRITICALERRORS into the inherited error mode at app
        # boot so the shell pop-ups stay suppressed even when the user
        # explicitly mounts a half-written partition.
        _kernel32.SetErrorMode.argtypes = [wintypes.UINT]
        _kernel32.SetErrorMode.restype = wintypes.UINT
        _kernel32.GetErrorMode.argtypes = []
        _kernel32.GetErrorMode.restype = wintypes.UINT
    return _kernel32
