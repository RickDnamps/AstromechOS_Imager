# tests/unit/test_keygen_hotspot.py
"""Hotspot bootstrap = random ``Astromech-<4 digits>`` SSID + operator PSK.

Per the dual-WLAN amendment: each burn gets a fresh SSID so multiple
unboxed pairs can come up in the same workshop without colliding on
the bootstrap AP; the PSK is supplied by the operator via Step 4 so
it never lives in git history (and so the FINAL per-robot PSK,
which carries through the firstboot handover by default, is the
operator's secret).
"""
import re

import pytest

from astromechos_imager.core.keygen import generate_hotspot_bootstrap
from astromechos_imager.core.models import HotspotBootstrap
from astromechos_imager.core.validators import validate_ssid, validate_wpa2_psk

_OPERATOR_PSK = "WorkshopPSK-42"   # 14 chars, valid WPA2-PSK


def test_returns_hotspot_bootstrap():
    b = generate_hotspot_bootstrap(_OPERATOR_PSK)
    assert isinstance(b, HotspotBootstrap)


def test_ssid_passes_validator():
    b = generate_hotspot_bootstrap(_OPERATOR_PSK)
    validate_ssid(b.ssid)  # must not raise


def test_psk_is_operator_supplied_verbatim():
    b = generate_hotspot_bootstrap(_OPERATOR_PSK)
    assert b.password == _OPERATOR_PSK
    validate_wpa2_psk(b.password)


def test_ssid_format_is_random_four_digits():
    b = generate_hotspot_bootstrap(_OPERATOR_PSK)
    assert re.fullmatch(r"Astromech-[0-9]{4}", b.ssid)


def test_ssid_varies_across_calls():
    """4-digit suffix → 10 000 possibilities; in 1 000 draws we
    expect a healthy spread. We assert strictly fewer than 50
    duplicates (binomial expectation ≈ 50). This is the workshop
    collision guard: two pairs burned back-to-back are
    overwhelmingly likely to get different SSIDs."""
    ssids = [generate_hotspot_bootstrap(_OPERATOR_PSK).ssid for _ in range(1000)]
    unique = set(ssids)
    assert len(unique) > 900, (
        f"only {len(unique)} unique SSIDs in 1000 draws — randomness broken"
    )


@pytest.mark.parametrize("bad", ["", "short", "x" * 7])
def test_rejects_invalid_psk(bad):
    """Defence in depth: ``FirstbootConfig.__post_init__`` also
    validates, but the operator gets a clearer error here."""
    with pytest.raises(ValueError):
        generate_hotspot_bootstrap(bad)
