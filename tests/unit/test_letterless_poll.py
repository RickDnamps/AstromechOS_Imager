"""The 2 s UI poll never touches drive letters.

The per-disk ASSOCIATORS letter query materialises Win32_LogicalDisk inside
WmiPrvSE - out of our process, beyond SetErrorMode - and touching a lettered
RAW/ext4 volume there pops "Format this disk?". These tests pin: (a)
enumerate_removable_drives(include_letters=False) skips that query entirely,
(b) DriveListModel polls letterless with a TypeError fallback for fakes,
(c) suspect FIXED disks are excluded from scan-time letter stripping.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from astromechos_imager.core.models import DiskRef


def _disk(phys_id=2, media_type="Removable Media", letters=("K",)):
    return DiskRef(
        physical_drive_id=phys_id,
        device_path=f"\\\\.\\PHYSICALDRIVE{phys_id}",
        drive_letters=letters,
        size_bytes=64 * 1024**3,
        model="Test Reader",
        serial="S1",
        media_type=media_type,
    )


def test_diskref_media_type_default_not_suspect():
    d = DiskRef(2, "\\\\.\\PHYSICALDRIVE2", ("K",), 1024, "m", "s")
    assert d.media_type == ""
    assert d.is_suspect_fixed is False


def test_diskref_fixed_media_is_suspect():
    assert _disk(media_type="Fixed hard disk media").is_suspect_fixed is True
    assert _disk(media_type="Removable Media").is_suspect_fixed is False


@pytest.mark.skipif(sys.platform != "win32", reason="windows module")
def test_enumerate_letterless_skips_associators(monkeypatch):
    from astromechos_imager.platform import windows as W

    wmi_disk = SimpleNamespace(
        DeviceID="\\\\.\\PHYSICALDRIVE2", Size=str(64 * 1024**3),
        Model="Test Reader", SerialNumber="S1",
        InterfaceType="USB", MediaType="Removable Media",
    )
    monkeypatch.setattr(W, "_wmi_query", lambda: [wmi_disk])
    monkeypatch.setattr(W, "_system_drive_id", lambda: 0)

    def boom(device_id):
        raise AssertionError("letter query must NOT run letterless")

    monkeypatch.setattr(W, "_drive_letters_for", boom)
    drives = list(W.enumerate_removable_drives(include_letters=False))
    assert len(drives) == 1
    assert drives[0].drive_letters == ()
    assert drives[0].media_type == "Removable Media"


class _FakePlatformNoKwarg:
    """Old-style PlatformIO without the include_letters kwarg."""

    def __init__(self, drives):
        self._drives = drives
        self.calls = 0

    def enumerate_removable_drives(self):
        self.calls += 1
        return list(self._drives)


class _FakePlatformKwarg(_FakePlatformNoKwarg):
    def enumerate_removable_drives(self, include_letters=True):
        self.calls += 1
        self.last_include_letters = include_letters
        return list(self._drives)


@pytest.fixture()
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def test_model_polls_letterless_when_supported(qapp):
    from astromechos_imager.ui.drive_list_model import DriveListModel
    pio = _FakePlatformKwarg([_disk()])
    model = DriveListModel(pio)
    assert pio.last_include_letters is False
    assert model.count == 1


def test_model_falls_back_for_old_fakes(qapp):
    from astromechos_imager.ui.drive_list_model import DriveListModel
    pio = _FakePlatformNoKwarg([_disk()])
    model = DriveListModel(pio)
    assert model.count == 1
    assert pio.calls >= 1


def test_strippable_ids_exclude_suspect_fixed(qapp):
    from astromechos_imager.ui.drive_list_model import DriveListModel
    pio = _FakePlatformKwarg([
        _disk(phys_id=2, media_type="Removable Media"),
        _disk(phys_id=3, media_type="Fixed hard disk media"),
    ])
    model = DriveListModel(pio)
    assert model.strippable_drive_ids() == [2]
