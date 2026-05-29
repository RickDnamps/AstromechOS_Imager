# tests/unit/test_keygen_hotspot.py
import re
import pytest
from astromechos_imager.core.keygen import generate_hotspot_bootstrap
from astromechos_imager.core.validators import validate_ssid, validate_wpa2_psk
from astromechos_imager.core.models import HotspotBootstrap


def test_returns_hotspot_bootstrap():
    b = generate_hotspot_bootstrap()
    assert isinstance(b, HotspotBootstrap)


def test_ssid_passes_validator():
    b = generate_hotspot_bootstrap()
    validate_ssid(b.ssid)  # must not raise


def test_psk_passes_validator():
    b = generate_hotspot_bootstrap()
    validate_wpa2_psk(b.password)


def test_ssid_format():
    b = generate_hotspot_bootstrap()
    assert re.match(r"^Astromech_Boot_[0-9A-F]{4}$", b.ssid)


def test_psk_is_32_hex():
    b = generate_hotspot_bootstrap()
    assert len(b.password) == 32
    int(b.password, 16)  # parses


def test_collision_probability_is_low():
    # 1000 calls should produce no collisions on the 16-bit SSID suffix in practice
    # (we just want different PSKs every call — SSID collisions are rare but legal)
    seen_psks = {generate_hotspot_bootstrap().password for _ in range(1000)}
    assert len(seen_psks) == 1000
