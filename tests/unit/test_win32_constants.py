"""Tests for Win32 constants. Runs on Windows; skipped elsewhere."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


def test_constants_match_winioctl():
    from astromechos_imager.platform._win32 import (
        FILE_FLAG_NO_BUFFERING,
        FILE_FLAG_WRITE_THROUGH,
        FILE_SHARE_READ,
        FILE_SHARE_WRITE,
        FSCTL_DISMOUNT_VOLUME,
        FSCTL_LOCK_VOLUME,
        GENERIC_READ,
        GENERIC_WRITE,
        INVALID_HANDLE_VALUE,
        IOCTL_DISK_GET_DRIVE_GEOMETRY_EX,
        IOCTL_DISK_UPDATE_PROPERTIES,
        IOCTL_STORAGE_EJECT_MEDIA,
        OPEN_EXISTING,
    )
    assert GENERIC_READ == 0x80000000
    assert GENERIC_WRITE == 0x40000000
    assert FILE_SHARE_READ == 0x00000001
    assert FILE_SHARE_WRITE == 0x00000002
    assert OPEN_EXISTING == 3
    assert FILE_FLAG_NO_BUFFERING == 0x20000000
    assert FILE_FLAG_WRITE_THROUGH == 0x80000000
    assert FSCTL_LOCK_VOLUME == 0x00090018
    assert FSCTL_DISMOUNT_VOLUME == 0x00090020
    assert IOCTL_DISK_UPDATE_PROPERTIES == 0x00070140
    assert IOCTL_STORAGE_EJECT_MEDIA == 0x002D4808
    assert IOCTL_DISK_GET_DRIVE_GEOMETRY_EX == 0x000700A0
    # (HANDLE)-1 as ctypes surfaces it from a c_void_p restype: the UNSIGNED
    # pointer value, not Python's signed -1. This MUST match what CreateFileW
    # actually returns on FAILURE, or failed opens slip through the
    # `h == INVALID_HANDLE_VALUE` guard and the bogus handle reaches
    # SetFilePointerEx/WriteFile (→ ERROR_INVALID_HANDLE / errno 6). On win64
    # that's 0xFFFFFFFFFFFFFFFF.
    import ctypes
    assert ctypes.c_void_p(-1).value == INVALID_HANDLE_VALUE
    assert INVALID_HANDLE_VALUE != -1  # the old, broken sentinel
