# tests/unit/test_pair_symmetry.py
import pytest
from astromechos_imager.core.customization import (
    FirstbootBundle, assert_pair_symmetry,
)
from astromechos_imager.core.errors import PairAsymmetryError
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _setup_pair(fake_boot_partition_factory):
    pair = generate_ed25519()
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"),
    )
    master_bp = fake_boot_partition_factory()
    slave_bp = fake_boot_partition_factory()
    bundle = FirstbootBundle(cfg, pair)
    bundle.write_to(master_bp, Role.MASTER)
    bundle.write_to(slave_bp, Role.SLAVE)
    return master_bp, slave_bp, cfg


@pytest.fixture
def fake_boot_partition_factory(fake_boot_partition):
    # Return a callable creating fresh fakes — reuse the same class
    def _make():
        return type(fake_boot_partition)()
    return _make


def test_symmetric_pair_passes(fake_boot_partition_factory):
    m, s, _ = _setup_pair(fake_boot_partition_factory)
    assert_pair_symmetry(m, s)  # must not raise


def test_asymmetric_hotspot_raises(fake_boot_partition_factory):
    m, s, cfg = _setup_pair(fake_boot_partition_factory)
    # Tamper with slave's init.cfg [hotspot]
    text = s.read_bytes("/astromech_init.cfg").decode().replace(
        f"ssid = {cfg.hotspot_bootstrap.ssid}",
        "ssid = Astromech-9999"
    )
    s.write_bytes("/astromech_init.cfg", text.encode())
    with pytest.raises(PairAsymmetryError):
        assert_pair_symmetry(m, s)
