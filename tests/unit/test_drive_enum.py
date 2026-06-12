"""Tests for WMI-based drive enumeration. WMI calls are mocked."""
from unittest.mock import MagicMock, patch

from astromechos_imager.platform.windows import enumerate_removable_drives


def _wmi_disk(device_id, size, model, serial, interface_type, media_type):
    m = MagicMock()
    m.DeviceID = device_id
    m.Size = str(size)
    m.Model = model
    m.SerialNumber = serial
    m.InterfaceType = interface_type
    m.MediaType = media_type
    return m


def test_filters_to_removable_usb(monkeypatch):
    fake_drives = [
        _wmi_disk(r"\\.\PHYSICALDRIVE0", 1_000_000_000_000, "Samsung SSD", "INTERNAL",
                  "SATA", "Fixed hard disk media"),
        _wmi_disk(r"\\.\PHYSICALDRIVE2", 32_000_000_000, "SanDisk Ultra", "USB-1",
                  "USB", "Removable Media"),
        _wmi_disk(r"\\.\PHYSICALDRIVE3", 16_000_000_000, "Some USB stick", "USB-2",
                  "USB", "Removable Media"),
    ]
    with patch("astromechos_imager.platform.windows._wmi_query") as q:
        q.return_value = fake_drives
        with patch("astromechos_imager.platform.windows._drive_letters_for") as letters:
            letters.side_effect = lambda did: ("E",) if "DRIVE2" in did else ("F",)
            with patch("astromechos_imager.platform.windows._system_drive_id") as sd:
                sd.return_value = 0  # PHYSICALDRIVE0 is system
                drives = list(enumerate_removable_drives())
    ids = [d.physical_drive_id for d in drives]
    assert 0 not in ids  # system drive excluded
    assert 2 in ids and 3 in ids
    e = next(d for d in drives if d.physical_drive_id == 2)
    assert e.drive_letters == ("E",)
    assert e.model == "SanDisk Ultra"


def test_excludes_drives_over_256gb(monkeypatch):
    fake_drives = [
        _wmi_disk(r"\\.\PHYSICALDRIVE5", 500_000_000_000, "Huge USB drive",
                  "TOO_BIG", "USB", "Removable Media"),
    ]
    with patch("astromechos_imager.platform.windows._wmi_query") as q:
        q.return_value = fake_drives
        with patch("astromechos_imager.platform.windows._drive_letters_for", return_value=()):
            with patch("astromechos_imager.platform.windows._system_drive_id", return_value=0):
                drives = list(enumerate_removable_drives())
    assert drives == []
