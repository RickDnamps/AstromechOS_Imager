# tests/unit/test_render_wlan_conf.py
"""Golden-case tests for render_wlan_conf() — Phase 8.10."""
import pytest
from astromechos_imager.core.customization import render_wlan_conf


def test_basic_case():
    """Basic SSID + PSK produces the expected flat key=value payload."""
    result = render_wlan_conf("Home", "secret12")
    assert result == b"SSID=Home\nPSK=secret12\n"


def test_unicode_ssid_produces_valid_utf8():
    """Unicode SSID (e.g., accented character) is encoded as UTF-8."""
    result = render_wlan_conf("Café", "secret12")
    assert result.startswith(b"SSID=Caf")
    # Verify round-trip: decodes back as UTF-8 without error
    text = result.decode("utf-8")
    assert "SSID=Café" in text
    assert "PSK=secret12" in text


def test_psk_with_special_chars():
    """PSK containing spaces, @, ! are included verbatim."""
    result = render_wlan_conf("Home", "p@ss w0rd!")
    assert b"PSK=p@ss w0rd!" in result


def test_trailing_newline_always_present():
    """Output always ends with a newline — required for shell source compatibility."""
    result = render_wlan_conf("Net", "12345678")
    assert result.endswith(b"\n")


def test_format_has_exactly_two_lines():
    """Output is exactly two lines: SSID=... and PSK=..."""
    result = render_wlan_conf("MyNetwork", "passphrase1")
    lines = result.decode("utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("SSID=")
    assert lines[1].startswith("PSK=")


def test_no_header_comments():
    """Output must contain NO comment lines (# ...) — stays shell-parseable."""
    result = render_wlan_conf("Net", "12345678")
    text = result.decode("utf-8")
    for line in text.splitlines():
        assert not line.startswith("#"), f"Unexpected comment line: {line!r}"


def test_ssid_value_exact():
    """SSID value is exactly as passed — no trimming or escaping."""
    result = render_wlan_conf("Réseau-Maison", "mypassword")
    text = result.decode("utf-8")
    assert "SSID=Réseau-Maison" in text


def test_psk_value_exact():
    """PSK value is exactly as passed."""
    result = render_wlan_conf("SomeNet", "correct horse battery staple")
    text = result.decode("utf-8")
    assert "PSK=correct horse battery staple" in text
