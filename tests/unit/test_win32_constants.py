"""Tests for Win32 constants. Runs on Windows; skipped elsewhere."""
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


def test_constants_match_winioctl():
    from astromechos_imager.platform._win32 import (
        GENERIC_READ, GENERIC_WRITE, FILE_SHARE_READ, FILE_SHARE_WRITE,
        OPEN_EXISTING, FILE_FLAG_NO_BUFFERING, FILE_FLAG_WRITE_THROUGH,
        FSCTL_LOCK_VOLUME, FSCTL_DISMOUNT_VOLUME,
        IOCTL_DISK_UPDATE_PROPERTIES, IOCTL_STORAGE_EJECT_MEDIA,
        IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, INVALID_HANDLE_VALUE,
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
    assert INVALID_HANDLE_VALUE == -1
