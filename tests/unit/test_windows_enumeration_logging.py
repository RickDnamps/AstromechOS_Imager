"""Verify enumerate_removable_drives() logs every candidate decision.

This is the regression that masked the JMicron USB-SATA bridge bug: an
SD card behind such a bridge advertises ``InterfaceType=SCSI`` +
``MediaType="Fixed hard disk media"`` and was silently dropped by the
filter with zero log output, so users saw "SD card not detected" with
no way to diagnose why.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch


def _wmi_disk(device_id, size, model, serial, interface_type, media_type):
    m = MagicMock()
    m.DeviceID = device_id
    m.Size = str(size)
    m.Model = model
    m.SerialNumber = serial
    m.InterfaceType = interface_type
    m.MediaType = media_type
    return m


def _enumerate(candidates, sys_id: int = 0, letters: tuple[str, ...] = ()):
    from astromechos_imager.platform.windows import enumerate_removable_drives
    with (
        patch("astromechos_imager.platform.windows._wmi_query",
              return_value=candidates),
        patch("astromechos_imager.platform.windows._drive_letters_for",
              return_value=letters),
        patch("astromechos_imager.platform.windows._system_drive_id",
              return_value=sys_id),
    ):
        return list(enumerate_removable_drives())


def test_enumerate_logs_wmi_candidate_count(caplog):
    candidate = _wmi_disk(r"\\.\PHYSICALDRIVE2", 32_000_000_000,
                          "SanDisk Ultra", "USB-1", "USB", "Removable Media")
    with caplog.at_level(logging.INFO,
                         logger="astromechos_imager.platform.windows"):
        _enumerate([candidate])
    messages = "\n".join(rec.message for rec in caplog.records)
    assert "enumerate_removable_drives: WMI returned 1 candidate disk(s)" in messages


def test_enumerate_logs_reject_reason_for_sata_bridge(caplog):
    """The SD-behind-JMicron-bridge case: SCSI + 'Fixed hard disk media'."""
    candidate = _wmi_disk(r"\\.\PHYSICALDRIVE3", 32_000_000_000,
                          "JMicron Bridge", "BR-1", "SCSI",
                          "Fixed hard disk media")
    with caplog.at_level(logging.INFO,
                         logger="astromechos_imager.platform.windows"):
        result = _enumerate([candidate])
    assert result == []
    messages = "\n".join(rec.message for rec in caplog.records)
    assert "reject \\\\.\\PHYSICALDRIVE3" in messages
    assert "not USB and not removable" in messages
    assert "interface=SCSI" in messages


def test_enumerate_logs_accept_for_usb_stick(caplog):
    candidate = _wmi_disk(r"\\.\PHYSICALDRIVE2", 32_000_000_000,
                          "SanDisk Ultra", "USB-1", "USB", "Removable Media")
    with caplog.at_level(logging.INFO,
                         logger="astromechos_imager.platform.windows"):
        result = _enumerate([candidate], letters=("E",))
    assert len(result) == 1
    assert result[0].physical_drive_id == 2
    messages = "\n".join(rec.message for rec in caplog.records)
    assert "ACCEPT \\\\.\\PHYSICALDRIVE2" in messages
    assert "phys_id=2" in messages


def test_enumerate_logs_reject_for_oversize_drive(caplog):
    candidate = _wmi_disk(r"\\.\PHYSICALDRIVE5", 500_000_000_000,
                          "Huge USB drive", "BIG", "USB", "Removable Media")
    with caplog.at_level(logging.INFO,
                         logger="astromechos_imager.platform.windows"):
        result = _enumerate([candidate])
    assert result == []
    messages = "\n".join(rec.message for rec in caplog.records)
    assert "reject \\\\.\\PHYSICALDRIVE5" in messages
    assert "outside" in messages


def test_enumerate_logs_reject_for_system_drive(caplog):
    candidate = _wmi_disk(r"\\.\PHYSICALDRIVE0", 500_000_000_000,
                          "OS Drive", "OS", "USB", "Removable Media")
    with caplog.at_level(logging.INFO,
                         logger="astromechos_imager.platform.windows"):
        result = _enumerate([candidate], sys_id=0)
    assert result == []
    messages = "\n".join(rec.message for rec in caplog.records)
    assert "is the system drive" in messages
