# tests/unit/test_render_wlan_conf.py
"""Tests for render_wlan_conf() — Phase 8.10 + audit Info #51 hardening.

Values are now single-quoted with POSIX-correct escaping so SSIDs / PSKs
containing shell metacharacters (``$``, backticks, ``;``, ``"``, ``'``)
are safely passed to ``source`` / ``awk -F=`` on the Pi side. Embedded
newlines / NULs raise outright to make second-line injection impossible.
"""
import pytest
from astromechos_imager.core.customization import render_wlan_conf


def test_basic_case():
    """Basic SSID + PSK produces single-quoted key=value payload."""
    result = render_wlan_conf("Home", "secret12")
    assert result == b"SSID='Home'\nPSK='secret12'\n"


def test_unicode_ssid_produces_valid_utf8():
    """Unicode SSID (e.g., accented character) is encoded as UTF-8."""
    result = render_wlan_conf("Café", "secret12")
    text = result.decode("utf-8")
    assert "SSID='Café'" in text
    assert "PSK='secret12'" in text


def test_psk_with_special_chars():
    """PSK containing spaces, @, ! are included verbatim inside the quotes."""
    result = render_wlan_conf("Home", "p@ss w0rd!")
    assert b"PSK='p@ss w0rd!'" in result


def test_shell_metacharacters_in_ssid_are_neutralised():
    """``$`` / backticks / ``;`` inside SSID stay literal — no expansion."""
    result = render_wlan_conf("Net$(rm -rf)", "secret12").decode("utf-8")
    # Single-quoted block stops the shell expanding $(...), so the literal
    # characters are preserved in the file.
    assert "SSID='Net$(rm -rf)'" in result


def test_embedded_single_quote_is_escaped():
    """An ``'`` inside the value uses the ``'\\''`` POSIX trick."""
    result = render_wlan_conf("My'Wifi", "secret12").decode("utf-8")
    # POSIX: 'My' + \' + 'Wifi' parses back to My'Wifi when sh-sourced.
    assert "SSID='My'\\''Wifi'" in result


def test_embedded_newline_in_ssid_rejected():
    """Newline injection (second VAR= line) must be refused outright."""
    with pytest.raises(ValueError, match="newline"):
        render_wlan_conf("Net\nROOT=1", "secret12")


def test_embedded_newline_in_psk_rejected():
    with pytest.raises(ValueError, match="newline"):
        render_wlan_conf("Home", "secret\nEVIL=1")


def test_embedded_nul_rejected():
    with pytest.raises(ValueError, match="newline|NUL"):
        render_wlan_conf("Home", "secret\x00")


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
