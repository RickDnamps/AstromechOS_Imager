"""Backend non-blocking fallback tests for ``_build_flash_job``.

The hybrid migration moves the responsibility of "what gets written to
/boot/astromech_init.cfg when the operator leaves Step 4 blank" from
the QML layer down to ``flash_view_model._build_flash_job``. Blank UI
fields are silently substituted with ``DEFAULT_INSTALL_USER`` /
``DEFAULT_INSTALL_PASSWORD`` / ``DEFAULT_HOTSPOT_PASSWORD`` before the
``FirstbootConfig`` is built — so the resulting SD card is ALWAYS
complete (no firstboot brick-skip on empty hotspot password, no
unrecoverable mismatch between cold rootfs surgery target and
``[system] user``).

These tests pin the substitution contract so a regression that bypasses
the defaults would fail loud here instead of bricking a robot.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from astromechos_imager.ui.flash_view_model import (
    DEFAULT_HOTSPOT_PASSWORD,
    DEFAULT_INSTALL_PASSWORD,
    DEFAULT_INSTALL_USER,
    _build_flash_job,
)


def _fake_wizard(
    *,
    install_user: str = "",
    install_password: str = "",
    hotspot_password: str = "",
    wifi_ssid: str = "",
    wifi_psk: str = "",
) -> SimpleNamespace:
    """Minimal WizardState stand-in — _build_flash_job only reads attrs."""
    return SimpleNamespace(
        mode="master_only",
        masterImagePath=r"C:\nonexistent.img.xz",
        slaveImagePath="",
        masterDriveId=2,
        slaveDriveId=-1,
        hostnameMaster="astromech-master",
        hostnameSlave="astromech-slave",
        repoUrl="",
        reuseHotspot=False,
        wifiSsid=wifi_ssid,
        wifiPsk=wifi_psk,
        installUser=install_user,
        installPassword=install_password,
        hotspotPassword=hotspot_password,
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
    def __init__(self, drives):
        self._drives = drives

    def enumerate_removable_drives(self):
        return list(self._drives)


# ── DEFAULT constants are the documented values ───────────────────────


def test_defaults_match_documented_values():
    """Lock the surface — if these constants drift, the entire fleet
    of "operator left blank" deployments end up with a different
    username/password. Pin them explicitly."""
    assert DEFAULT_INSTALL_USER == "astromech"
    assert DEFAULT_INSTALL_PASSWORD == "astropass"
    assert DEFAULT_HOTSPOT_PASSWORD == "astropass"


# ── Empty fields → defaults substituted ───────────────────────────────


def test_empty_install_user_substitutes_default(tmp_path, monkeypatch):
    """The most important regression guard: an empty installUser must
    NOT propagate as ``""`` into the FirstbootConfig (the Pi-side
    ``capture_user`` would fall back to the legacy 'artoo' which the
    operator may not have, leading to a "user 'artoo' does not exist"
    abort)."""
    img = tmp_path / "img.xz"
    img.write_bytes(b"x")
    monkeypatch.setattr(
        "astromechos_imager.core.keygen.load_persisted_pair", lambda: None
    )
    monkeypatch.setattr(
        "astromechos_imager.core.keygen.load_persisted_hotspot", lambda: None
    )
    monkeypatch.setattr(
        "astromechos_imager.core.keygen.save_persisted_pair", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "astromechos_imager.core.keygen.save_persisted_hotspot", lambda *_a, **_k: None
    )

    wiz = _fake_wizard()
    wiz.masterImagePath = str(img)
    plat = _FakePlatformIO([_fake_drive(2)])

    job = _build_flash_job(wiz, platform_io=plat)
    assert job is not None
    assert job.linux_account.username == DEFAULT_INSTALL_USER
    assert job.linux_account.cleartext_password == DEFAULT_INSTALL_PASSWORD
    assert job.firstboot_config.install_user == DEFAULT_INSTALL_USER
    assert job.firstboot_config.hotspot_bootstrap.password == DEFAULT_HOTSPOT_PASSWORD
    # Wi-Fi remains None (optional, both empty)
    assert job.firstboot_config.wifi_ssid is None
    assert job.firstboot_config.wifi_psk is None


# ── Operator override wins over defaults ──────────────────────────────


def test_operator_override_wins_over_default(tmp_path, monkeypatch):
    img = tmp_path / "img.xz"
    img.write_bytes(b"x")
    for fname in (
        "load_persisted_pair", "load_persisted_hotspot",
        "save_persisted_pair", "save_persisted_hotspot",
    ):
        monkeypatch.setattr(
            f"astromechos_imager.core.keygen.{fname}", lambda *_a, **_k: None
        )

    wiz = _fake_wizard(
        install_user="r2d2",
        install_password="mySecret123",
        hotspot_password="hotspotSecret",
    )
    wiz.masterImagePath = str(img)
    plat = _FakePlatformIO([_fake_drive(2)])

    job = _build_flash_job(wiz, platform_io=plat)
    assert job.linux_account.username == "r2d2"
    assert job.linux_account.cleartext_password == "mySecret123"
    assert job.firstboot_config.install_user == "r2d2"
    assert job.firstboot_config.hotspot_bootstrap.password == "hotspotSecret"


# ── Whitespace-only username treated as empty ─────────────────────────


def test_whitespace_only_username_substitutes_default(tmp_path, monkeypatch):
    """Operator who hits SPACE in the field by accident shouldn't get
    a UID-1000 row named ' ' on the SD card. ``.strip()`` collapses
    it to empty, then the default substitution kicks in."""
    img = tmp_path / "img.xz"
    img.write_bytes(b"x")
    for fname in (
        "load_persisted_pair", "load_persisted_hotspot",
        "save_persisted_pair", "save_persisted_hotspot",
    ):
        monkeypatch.setattr(
            f"astromechos_imager.core.keygen.{fname}", lambda *_a, **_k: None
        )

    wiz = _fake_wizard(install_user="   ")
    wiz.masterImagePath = str(img)
    plat = _FakePlatformIO([_fake_drive(2)])

    job = _build_flash_job(wiz, platform_io=plat)
    assert job.linux_account.username == DEFAULT_INSTALL_USER


# ── Wi-Fi half-config is still rejected ───────────────────────────────


def test_half_filled_wifi_raises(tmp_path, monkeypatch):
    """Wi-Fi is fully optional; setting SSID without PSK (or vice-versa)
    leaves the Pi side trying to associate to an open AP. Reject
    early with a clear message instead of letting
    ``astromech_wlan_setup.sh`` create a misconfigured profile."""
    img = tmp_path / "img.xz"
    img.write_bytes(b"x")
    for fname in (
        "load_persisted_pair", "load_persisted_hotspot",
        "save_persisted_pair", "save_persisted_hotspot",
    ):
        monkeypatch.setattr(
            f"astromechos_imager.core.keygen.{fname}", lambda *_a, **_k: None
        )

    wiz = _fake_wizard(wifi_ssid="MyNet")  # PSK empty
    wiz.masterImagePath = str(img)
    plat = _FakePlatformIO([_fake_drive(2)])

    with pytest.raises(Exception):  # RuntimeError ducktyped from FirstbootConfig path
        _build_flash_job(wiz, platform_io=plat)
