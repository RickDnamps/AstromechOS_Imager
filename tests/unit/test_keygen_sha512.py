"""Regression tests for SHA-512 crypt hash generation.

Catches the 82->86 char truncation bug that was present until 2026-06-03.
"""
import re

from astromechos_imager.core.keygen import _sha512_crypt


def test_sha512_crypt_hash_portion_is_exactly_86_chars():
    """The hash portion after $6$<salt>$ must be exactly 86 characters."""
    result = _sha512_crypt("astropass123", "KB0oWRHVHtLAfrOZ", 5000)
    parts = result.split("$")
    # parts = ['', '6', '<salt>', '<hash>']
    assert len(parts) == 4, f"unexpected format: {result}"
    assert parts[1] == "6"
    assert parts[2] == "KB0oWRHVHtLAfrOZ"
    assert len(parts[3]) == 86, (
        f"hash portion is {len(parts[3])} chars, expected 86 - "
        f"truncation regression: {result}"
    )


def test_sha512_crypt_matches_known_openssl_output():
    """Cross-validate against a known openssl crypt(3) output.

    Computed via: openssl passwd -6 -salt KB0oWRHVHtLAfrOZ astropass123
    """
    expected = (
        "$6$KB0oWRHVHtLAfrOZ$2sjGNQE2vGaLKxIlGu94621W3Nh2idBGKYSRcK9z8fYJv"
        "eWblImsiE5vGTDmL0MLy5BJJSmZYVgXx7JSRm7bs1"
    )
    result = _sha512_crypt("astropass123", "KB0oWRHVHtLAfrOZ", 5000)
    assert result == expected, f"mismatch:\n  got: {result}\n  exp: {expected}"


def test_sha512_crypt_format_regex():
    """The output must match the standard crypt format pattern."""
    result = _sha512_crypt("test", "abcd1234", 5000)
    # $6$<8-16 char salt>$<86-char hash from [./0-9A-Za-z]>
    pattern = r"^\$6\$[./0-9A-Za-z]{1,16}\$[./0-9A-Za-z]{86}$"
    assert re.match(pattern, result), f"bad format: {result}"


def test_sha512_crypt_different_passwords_give_different_hashes():
    """Sanity: different inputs -> different outputs."""
    salt = "abcd1234"
    h1 = _sha512_crypt("password1", salt, 5000)
    h2 = _sha512_crypt("password2", salt, 5000)
    assert h1 != h2


def test_sha512_crypt_same_input_is_deterministic():
    """Deterministic for fixed salt + rounds."""
    salt = "abcd1234"
    h1 = _sha512_crypt("samepass", salt, 5000)
    h2 = _sha512_crypt("samepass", salt, 5000)
    assert h1 == h2
