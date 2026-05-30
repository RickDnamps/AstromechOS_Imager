# tests/unit/test_firstboot_config.py
import pytest
from pathlib import Path
from astromechos_imager.core.models import FirstbootConfig, HotspotBootstrap
from astromechos_imager.core.errors import (
    InvalidHostnameError, InvalidAuthorizedKeysError, InvalidRepoUrlError,
    InvalidWifiSsidError, InvalidWifiPskError,
)


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY user@host"


def test_minimal_valid():
    cfg = FirstbootConfig(authorized_keys=[VALID_KEY])
    assert cfg.install_user == "pi"
    assert cfg.hostname_master == "astromech-master"
    assert cfg.hostname_slave == "astromech-slave"
    assert cfg.repo_url is None
    assert cfg.hotspot_bootstrap is None


def test_with_all_fields():
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        install_user="astromech",
        repo_url="https://github.com/me/fork.git",
        repo_branch="develop",
        hostname_master="r2-dome",
        hostname_slave="r2-body",
        hotspot_bootstrap=HotspotBootstrap(ssid="Astromech-3742", password="a" * 16),
    )
    assert cfg.repo_branch == "develop"


def test_rejects_invalid_hostname():
    with pytest.raises(InvalidHostnameError):
        FirstbootConfig(authorized_keys=[VALID_KEY], hostname_master="bad host")


def test_accepts_empty_keys_zero_touch():
    """Empty authorized_keys is permitted under the Zero-Touch contract
    (see ``core/validators.py::validate_authorized_keys`` docstring)."""
    cfg = FirstbootConfig(authorized_keys=[])
    assert cfg.authorized_keys == []


def test_rejects_invalid_repo_url():
    with pytest.raises(InvalidRepoUrlError):
        FirstbootConfig(authorized_keys=[VALID_KEY], repo_url="ftp://no")


def test_frozen():
    cfg = FirstbootConfig(authorized_keys=[VALID_KEY])
    with pytest.raises(AttributeError):
        cfg.install_user = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 8.10 — optional WiFi fields on FirstbootConfig
# ---------------------------------------------------------------------------

def test_wifi_both_set_succeeds():
    """Providing both wifi_ssid and wifi_psk together is valid."""
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        wifi_ssid="Home",
        wifi_psk="secret12",
    )
    assert cfg.wifi_ssid == "Home"
    assert cfg.wifi_psk == "secret12"


def test_wifi_both_none_is_valid():
    """Default None/None is fully optional — no validation triggered."""
    cfg = FirstbootConfig(authorized_keys=[VALID_KEY])
    assert cfg.wifi_ssid is None
    assert cfg.wifi_psk is None


def test_wifi_both_empty_string_is_valid():
    """Empty string for both is treated as 'not provided'."""
    cfg = FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid="", wifi_psk="")
    assert cfg.wifi_ssid == ""
    assert cfg.wifi_psk == ""


def test_wifi_ssid_only_raises():
    """Providing wifi_ssid without wifi_psk must raise InvalidWifiSsidError."""
    with pytest.raises(InvalidWifiSsidError):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid="Home")


def test_wifi_psk_only_raises():
    """Providing wifi_psk without wifi_ssid must raise (paired requirement)."""
    with pytest.raises((InvalidWifiSsidError, InvalidWifiPskError)):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_psk="secret12")


def test_wifi_empty_ssid_with_psk_raises():
    """Empty SSID with a non-empty PSK is a half-config — must raise."""
    with pytest.raises((InvalidWifiSsidError, InvalidWifiPskError)):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid="", wifi_psk="secret12")


def test_wifi_ssid_with_empty_psk_raises():
    """Non-empty SSID with empty PSK is a half-config — must raise."""
    with pytest.raises((InvalidWifiSsidError, InvalidWifiPskError)):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid="Home", wifi_psk="")


def test_wifi_invalid_ssid_empty_raises():
    """Empty SSID (after strip) with valid PSK raises InvalidWifiSsidError."""
    with pytest.raises(InvalidWifiSsidError):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid="   ", wifi_psk="secret12")


def test_wifi_invalid_ssid_too_long_raises():
    """SSID exceeding 32 UTF-8 bytes raises InvalidWifiSsidError."""
    long_ssid = "A" * 33
    with pytest.raises(InvalidWifiSsidError):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid=long_ssid, wifi_psk="secret12")


def test_wifi_invalid_psk_too_short_raises():
    """PSK shorter than 8 chars raises InvalidWifiPskError."""
    with pytest.raises(InvalidWifiPskError):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid="Home", wifi_psk="short")


def test_wifi_invalid_psk_too_long_raises():
    """PSK longer than 63 chars raises InvalidWifiPskError."""
    with pytest.raises(InvalidWifiPskError):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid="Home", wifi_psk="a" * 64)


def test_wifi_invalid_psk_non_printable_raises():
    """PSK with non-printable chars raises InvalidWifiPskError."""
    with pytest.raises(InvalidWifiPskError):
        FirstbootConfig(authorized_keys=[VALID_KEY], wifi_ssid="Home", wifi_psk="pass\x00word!")


def test_wifi_unicode_ssid_valid():
    """Unicode SSID within 32-byte UTF-8 limit is valid."""
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        wifi_ssid="Réseau",
        wifi_psk="secret12",
    )
    assert cfg.wifi_ssid == "Réseau"


def test_wifi_ssid_exactly_32_bytes_valid():
    """SSID of exactly 32 ASCII bytes is valid."""
    ssid = "A" * 32
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        wifi_ssid=ssid,
        wifi_psk="secret12",
    )
    assert cfg.wifi_ssid == ssid
