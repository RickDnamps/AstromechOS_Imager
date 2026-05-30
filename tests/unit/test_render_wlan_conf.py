# tests/unit/test_render_wlan_conf.py
"""Tests for ``render_wlan_conf()`` — INI ``[home_wifi]`` format.

The live ``astromech_wlan_setup.sh:81-92`` parses the file with awk
keyed on the section header ``[home_wifi]`` and the keys ``ssid`` /
``password``. Match it byte-for-byte. ``key_mgmt = wpa-psk`` is written
as a documentary field — the awk parser ignores it but it pins the
WPA2-PSK contract that the Pi-side scripts already hard-code at
NM-creation time.
"""
import pytest

from astromechos_imager.core.customization import render_wlan_conf


def test_basic_case():
    """Basic SSID + PSK → ``[home_wifi]`` INI payload."""
    result = render_wlan_conf("Home", "secret12")
    assert result == (
        b"[home_wifi]\n"
        b"ssid = Home\n"
        b"password = secret12\n"
        b"key_mgmt = wpa-psk\n"
    )


def test_unicode_ssid_produces_valid_utf8():
    """Unicode SSID is encoded as UTF-8 — IEEE 802.11 permits non-ASCII."""
    result = render_wlan_conf("Café", "secret12")
    text = result.decode("utf-8")
    assert "ssid = Café" in text
    assert "password = secret12" in text


def test_psk_with_special_chars_passes_verbatim():
    """The live awk ``gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)`` only
    strips surrounding whitespace, so special chars in the middle of the
    value are preserved exactly."""
    result = render_wlan_conf("Home", "p@ss w0rd!").decode("utf-8")
    assert "password = p@ss w0rd!" in result


def test_embedded_newline_in_ssid_rejected():
    """Newline injection (second INI line) must be refused outright."""
    with pytest.raises(ValueError, match="newline"):
        render_wlan_conf("Net\n[evil]\nfoo=1", "secret12")


def test_embedded_newline_in_psk_rejected():
    with pytest.raises(ValueError, match="newline"):
        render_wlan_conf("Home", "secret\nEVIL=1")


def test_embedded_nul_rejected():
    with pytest.raises(ValueError, match="newline|NUL"):
        render_wlan_conf("Home", "secret\x00")


def test_trailing_newline_always_present():
    """Output always ends with a newline — last INI line gets terminated."""
    result = render_wlan_conf("Net", "12345678")
    assert result.endswith(b"\n")


def test_starts_with_home_wifi_section_header():
    """``astromech_wlan_setup.sh`` awk anchors on ``[home_wifi]`` —
    section header MUST be the first line."""
    result = render_wlan_conf("Net", "12345678").decode("utf-8")
    assert result.splitlines()[0] == "[home_wifi]"


def test_key_names_match_live_awk_parser():
    """The awk parser keys on ``ssid`` and ``password`` literally
    (lib_config.sh:66-71). Both keys MUST appear with EXACTLY this
    spelling, lower-case, ``=`` separator."""
    text = render_wlan_conf("Net", "12345678").decode("utf-8")
    assert "ssid = " in text
    assert "password = " in text


def test_key_mgmt_declared_as_wpa_psk():
    """WPA2 contract is documented in-file even though the awk parser
    does not read it — the Pi enforces wpa-psk at NM-creation time."""
    text = render_wlan_conf("Net", "12345678").decode("utf-8")
    assert "key_mgmt = wpa-psk" in text
