"""Selection safety: source-disk SAFETY STOP + provenance stamp.

The target disk must never be the disk hosting the source image (the
operator's USB SSD passes the eligibility filter), and the GUI job must
stamp the provenance fields (imager version + flash timestamp) that feed
the generated /boot header.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from astromechos_imager import __version__
from astromechos_imager.ui.flash_view_model import _build_flash_job


def _fake_wizard(image_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        currentRole="master",
        masterImagePath=image_path,
        slaveImagePath="",
        masterDriveId=2,
        slaveDriveId=-1,
        hostnameMaster="astromech-master",
        hostnameSlave="astromech-slave",
        repoUrl="",
        wifiSsid="",
        wifiPsk="",
        installUser="",
        installPassword="",
        hotspotPassword="",
        hotspotSsid="Astromech-1234",
    )


def _fake_drive(physical_drive_id: int = 2):
    from astromechos_imager.core.models import DiskRef
    return DiskRef(
        physical_drive_id=physical_drive_id,
        device_path=rf"\\.\PHYSICALDRIVE{physical_drive_id}",
        drive_letters=("E",),
        size_bytes=32 * (1 << 30),
        model="Fake SD",
        serial=f"FAKE{physical_drive_id:03d}",
    )


class _FakePlatformIO:
    """source_disk_ids = what disk_ids_for_path reports for ANY path."""

    def __init__(self, drives, source_disk_ids=None):
        self._drives = drives
        self._source_disk_ids = source_disk_ids

    def enumerate_removable_drives(self):
        return list(self._drives)

    def disk_ids_for_path(self, path):
        if self._source_disk_ids is None:
            raise AttributeError  # pragma: no cover
        return list(self._source_disk_ids)


@pytest.fixture()
def keygen_stubbed(monkeypatch):
    monkeypatch.setattr(
        "astromechos_imager.core.keygen.load_persisted_pair", lambda: None)
    for name in ("save_persisted_pair", "save_persisted_hotspot"):
        monkeypatch.setattr(f"astromechos_imager.core.keygen.{name}",
                            lambda *_a, **_k: None)


def _image(tmp_path):
    img = tmp_path / "img.xz"
    img.write_bytes(b"x")
    return str(img)


def test_safety_stop_when_target_hosts_source(tmp_path, keygen_stubbed):
    wiz = _fake_wizard(_image(tmp_path))
    plat = _FakePlatformIO([_fake_drive(2)], source_disk_ids=[2])
    with pytest.raises(RuntimeError, match="SAFETY STOP"):
        _build_flash_job(wiz, platform_io=plat)


def test_no_stop_when_source_on_other_disk(tmp_path, keygen_stubbed):
    wiz = _fake_wizard(_image(tmp_path))
    plat = _FakePlatformIO([_fake_drive(2)], source_disk_ids=[0])
    job = _build_flash_job(wiz, platform_io=plat)
    assert job is not None
    assert job.target.physical_drive_id == 2


def test_guard_degrades_open_without_helper(tmp_path, keygen_stubbed):
    """A platform_io without disk_ids_for_path (old fakes) blocks nothing."""

    class _Bare:
        def __init__(self, drives):
            self._drives = drives

        def enumerate_removable_drives(self):
            return list(self._drives)

    job = _build_flash_job(_fake_wizard(_image(tmp_path)),
                           platform_io=_Bare([_fake_drive(2)]))
    assert job is not None


def test_gui_job_stamps_provenance(tmp_path, keygen_stubbed):
    wiz = _fake_wizard(_image(tmp_path))
    plat = _FakePlatformIO([_fake_drive(2)], source_disk_ids=[0])
    job = _build_flash_job(wiz, platform_io=plat)
    assert job.firstboot_config.imager_version == __version__
    assert job.firstboot_config.flashed_at_iso != ""


def test_cli_defaults_lockstep_with_gui():
    """The CLI --install-user / --install-password defaults must match the
    GUI's locked 'astromech' invariant, so a CLI flash produces the same
    account contract as a GUI flash."""
    from astromechos_imager.cli.main import build_parser
    from astromechos_imager.ui.flash_view_model import (
        DEFAULT_INSTALL_PASSWORD,
        DEFAULT_INSTALL_USER,
    )
    args = build_parser().parse_args([
        "flash", "--master-image", "m", "--master-drive", "2",
        "--keys-file", "k",
    ])
    assert args.install_user == DEFAULT_INSTALL_USER
    assert args.install_password == DEFAULT_INSTALL_PASSWORD
