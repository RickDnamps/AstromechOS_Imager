# tests/unit/test_firstboot_bundle.py
import json
import pytest
from astromechos_imager.core.customization import FirstbootBundle
from astromechos_imager.core.errors import BundleSelfValidationFailedError
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _cfg(**kw):
    base = dict(authorized_keys=[VALID_KEY], imager_version="0.1.0",
                flashed_at_iso="2026-05-29T02:15:00Z",
                hotspot_bootstrap=generate_hotspot_bootstrap())
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
