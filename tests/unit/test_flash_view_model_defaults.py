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
    current_role: str = "master",
) -> SimpleNamespace:
    """Minimal WizardState stand-in — _build_flash_job only reads attrs.

    Sequential workflow: each cycle flashes one role driven by
    ``currentRole``. Default to "master" so existing single-role
    expectations carry through.
    """
    return SimpleNamespace(
        currentRole=current_role,
        masterImagePath=r"C:\nonexistent.img.xz",
        slaveImagePath="",
        masterDriveId=2,
        slaveDriveId=-1,
        hostnameMaster="astromech-master",
        hostnameSlave="astromech-slave",
        repoUrl="",
        wifiSsid=wifi_ssid,
        wifiPsk=wifi_psk,
        installUser=install_user,
        installPassword=install_password,
        hotspotPassword=hotspot_password,
        hotspotSsid="Astromech-1234",   # early-minted by WizardState in prod
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


# ── Username is LOCKED; password / hotspot still override ─────────────


def test_username_locked_password_and_hotspot_still_override(tmp_path, monkeypatch):
    """The username is a FIXED system constant — any operator-supplied
    value is IGNORED so the flashed account name can never drift from the
    Golden's UID-1000 user that cloud-init's chpasswd targets. The PASSWORD
    and hotspot PSK remain fully dynamic."""
    img = tmp_path / "img.xz"
    img.write_bytes(b"x")
    for fname in (
        "load_persisted_pair",
        "save_persisted_pair", "save_persisted_hotspot",
    ):
        monkeypatch.setattr(
            f"astromechos_imager.core.keygen.{fname}", lambda *_a, **_k: None
        )

    wiz = _fake_wizard(
        install_user="r2d2",            # ignored — username is locked
        install_password="mySecret123",
        hotspot_password="hotspotSecret",
    )
    wiz.masterImagePath = str(img)
    plat = _FakePlatformIO([_fake_drive(2)])

    job = _build_flash_job(wiz, platform_io=plat)
    assert job.linux_account.username == DEFAULT_INSTALL_USER          # NOT r2d2
    assert job.firstboot_config.install_user == DEFAULT_INSTALL_USER   # NOT r2d2
    assert job.linux_account.cleartext_password == "mySecret123"       # password wins
    assert job.firstboot_config.hotspot_bootstrap.password == "hotspotSecret"
    # The bootstrap SSID comes from the early-generated wizardState.hotspotSsid
    assert job.firstboot_config.hotspot_bootstrap.ssid == "Astromech-1234"


# ── Username stays fixed regardless of any field content ──────────────


def test_username_always_fixed_constant(tmp_path, monkeypatch):
    """Whatever lands in the (now read-only) username field — blank,
    whitespace, or stray text — the flashed UID-1000 login is always the
    fixed ``DEFAULT_INSTALL_USER`` constant."""
    img = tmp_path / "img.xz"
    img.write_bytes(b"x")
    for fname in (
        "load_persisted_pair",
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
        "load_persisted_pair",
        "save_persisted_pair", "save_persisted_hotspot",
    ):
        monkeypatch.setattr(
            f"astromechos_imager.core.keygen.{fname}", lambda *_a, **_k: None
        )

    wiz = _fake_wizard(wifi_ssid="MyNet")  # PSK empty
    wiz.masterImagePath = str(img)
    plat = _FakePlatformIO([_fake_drive(2)])

    # Half WiFi config (SSID without PSK) is rejected by _build_flash_job.
    with pytest.raises(RuntimeError, match="both SSID and PSK"):
        _build_flash_job(wiz, platform_io=plat)
