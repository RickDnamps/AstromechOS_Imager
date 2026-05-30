# tests/unit/test_firstboot_bundle.py
import json
import pytest
from astromechos_imager.core.customization import FirstbootBundle, render_wlan_conf
from astromechos_imager.core.errors import BundleSelfValidationFailedError
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _cfg(**kw):
    base = dict(authorized_keys=[VALID_KEY], imager_version="0.1.0",
                flashed_at_iso="2026-05-29T02:15:00Z",
                hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"))
    base.update(kw)
    return FirstbootConfig(**base)


def test_master_bundle_writes_all_required_files(fake_boot_partition):
    pair = generate_ed25519()
    cfg = _cfg()
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    fp = fake_boot_partition
    assert fp.exists("/astromech_secrets/init_config.json")
    assert fp.exists("/astromech_secrets/authorized_keys")
    assert fp.exists("/astromech_secrets/id_ed25519")
    assert fp.exists("/astromech_secrets/id_ed25519.pub")
    assert fp.exists("/astromech_init.cfg")
    # Trigger LAST
    assert fp.exists("/ASTROMECH_FIRSTBOOT_READY")
    assert fp.read_bytes("/ASTROMECH_FIRSTBOOT_READY") == b""


def test_slave_bundle_no_keypair(fake_boot_partition):
    pair = generate_ed25519()
    FirstbootBundle(_cfg(), pair).write_to(fake_boot_partition, Role.SLAVE)
    fp = fake_boot_partition
    assert not fp.exists("/astromech_secrets/id_ed25519")
    assert not fp.exists("/astromech_secrets/id_ed25519.pub")
    # Slave authorized_keys must contain master's pub
    keys_text = fp.read_bytes("/astromech_secrets/authorized_keys").decode()
    assert pair.public_openssh.decode().strip() in keys_text


def test_init_config_json_role_correct(fake_boot_partition):
    pair = generate_ed25519()
    FirstbootBundle(_cfg(), pair).write_to(fake_boot_partition, Role.MASTER)
    obj = json.loads(fake_boot_partition.read_bytes("/astromech_secrets/init_config.json"))
    assert obj["role"] == "master"


def test_trigger_marker_not_written_when_validation_fails(fake_boot_partition, monkeypatch):
    """Critical safety invariant: validation failure must NOT produce a trigger marker."""
    pair = generate_ed25519()
    bundle = FirstbootBundle(_cfg(), pair)
    # Force self-validate to fail by corrupting init_config.json after step 2
    original_write = fake_boot_partition.write_bytes

    def corrupting_write(p, d):
        if p == "/astromech_secrets/init_config.json":
            d = b'{"role": "invalid", "hostname": "x"}'
        original_write(p, d)

    monkeypatch.setattr(fake_boot_partition, "write_bytes", corrupting_write)
    with pytest.raises((AssertionError, BundleSelfValidationFailedError)):
        bundle.write_to(fake_boot_partition, Role.MASTER)
    assert not fake_boot_partition.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_hotspot_section_byte_identical_in_init_cfg(fake_boot_partition):
    pair = generate_ed25519()
    cfg = _cfg()
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    text = fake_boot_partition.read_bytes("/astromech_init.cfg").decode()
    assert f"ssid = {cfg.hotspot_bootstrap.ssid}" in text
    assert f"password = {cfg.hotspot_bootstrap.password}" in text


# ---------------------------------------------------------------------------
# Phase 8.10 — WiFi provisioning (/astromech_wlan.conf)
# ---------------------------------------------------------------------------

def test_wlan_conf_written_when_both_creds_set(fake_boot_partition):
    """When wifi_ssid and wifi_psk are set, /astromech_wlan.conf is written."""
    pair = generate_ed25519()
    cfg = _cfg(wifi_ssid="HomeNet", wifi_psk="secret12")
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    assert fake_boot_partition.exists("/astromech_wlan.conf")


def test_wlan_conf_content_correct(fake_boot_partition):
    """Written /astromech_wlan.conf has the exact INI [home_wifi] format
    consumed by ``astromech_wlan_setup.sh``'s awk parser (live script
    lines 81-92)."""
    pair = generate_ed25519()
    cfg = _cfg(wifi_ssid="MySSID", wifi_psk="mypassword")
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    content = fake_boot_partition.read_bytes("/astromech_wlan.conf")
    assert content == (
        b"[home_wifi]\n"
        b"ssid = MySSID\n"
        b"password = mypassword\n"
        b"key_mgmt = wpa-psk\n"
    )


def test_wlan_conf_not_written_when_both_none(fake_boot_partition):
    """When both wifi_ssid and wifi_psk are None (default), no file is written."""
    pair = generate_ed25519()
    cfg = _cfg()  # no wifi_ssid, no wifi_psk
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    assert not fake_boot_partition.exists("/astromech_wlan.conf")


def test_wlan_conf_not_written_when_both_empty(fake_boot_partition):
    """When both wifi_ssid and wifi_psk are empty strings, no file is written."""
    pair = generate_ed25519()
    cfg = _cfg(wifi_ssid="", wifi_psk="")
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    assert not fake_boot_partition.exists("/astromech_wlan.conf")


def test_self_validate_passes_with_wlan_creds(fake_boot_partition):
    """_self_validate does not raise when wlan creds are set and file exists."""
    pair = generate_ed25519()
    cfg = _cfg(wifi_ssid="HomeNet", wifi_psk="secret12")
    # Should complete without raising
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    assert fake_boot_partition.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_self_validate_passes_without_wlan_creds(fake_boot_partition):
    """_self_validate does not raise when no wlan creds — file correctly absent."""
    pair = generate_ed25519()
    cfg = _cfg()
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    assert fake_boot_partition.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_wlan_conf_written_for_slave_role(fake_boot_partition):
    """WiFi conf is role-agnostic — slave also gets the file when creds are set."""
    pair = generate_ed25519()
    cfg = _cfg(wifi_ssid="HomeNet", wifi_psk="secret12")
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.SLAVE)
    assert fake_boot_partition.exists("/astromech_wlan.conf")
    content = fake_boot_partition.read_bytes("/astromech_wlan.conf")
    assert content == (
        b"[home_wifi]\n"
        b"ssid = HomeNet\n"
        b"password = secret12\n"
        b"key_mgmt = wpa-psk\n"
    )
