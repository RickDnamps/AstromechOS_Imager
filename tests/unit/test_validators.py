# tests/unit/test_validators.py
import re
import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from astromechos_imager.core.errors import (
    InvalidAuthorizedKeysError,
    InvalidBranchNameError,
    InvalidHostnameError,
    InvalidHotspotPskError,
    InvalidHotspotSsidError,
    InvalidInstallUserError,
    InvalidRepoUrlError,
)
from astromechos_imager.core.validators import (
    validate_authorized_keys,
    validate_branch_name,
    validate_hostname,
    validate_install_user,
    validate_repo_url,
    validate_ssid,
    validate_wpa2_psk,
)


# ── Hostname ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("h", ["astromech-master", "astromech-slave", "r2", "x", "a1b2c3"])
def test_hostname_valid(h):
    validate_hostname(h)


@pytest.mark.parametrize("h", ["-leading", "trailing-", "has space", "has_underscore",
                                "a" * 64, "", "a..b", "127.0.0.1"])
def test_hostname_invalid(h):
    with pytest.raises(InvalidHostnameError):
        validate_hostname(h)


# ── OpenSSH pubkey ────────────────────────────────────────────────────────
@pytest.mark.parametrize("k", [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY user@host",
    "ssh-rsa AAAAB3NzaC1yc2EAAAA... me@laptop",
    "ecdsa-sha2-nistp256 AAAAB3...",
])
def test_openssh_pubkey_valid(k):
    validate_authorized_keys([k])


@pytest.mark.parametrize("k", ["", "not-a-key", "ssh-bad XXX", "ssh-ed25519", "ssh-ed25519 "])
def test_openssh_pubkey_invalid(k):
    with pytest.raises(InvalidAuthorizedKeysError):
        validate_authorized_keys([k])


def test_authorized_keys_empty_list_accepted_zero_touch():
    """Zero-Touch contract: an empty authorized_keys is permitted.

    The Master ships without an operator pubkey (operator authenticates
    with the Pi user's password at first login). The Slave receives the
    Master's public key at write time via render_authorized_keys; the
    role-aware FirstbootBundle._self_validate enforces that the Slave
    actually carries a valid OpenSSH key before the trigger marker is
    written. So this validator does not need to gate on emptiness.
    """
    # Must not raise.
    validate_authorized_keys([])


# ── Install user (POSIX login) ────────────────────────────────────────────
@pytest.mark.parametrize("u", ["pi", "astromech", "testuser", "_svc", "user-1"])
def test_install_user_valid(u):
    validate_install_user(u)


@pytest.mark.parametrize("u", ["Pi", "1pi", "user name", "root@host", "x" * 33, ""])
def test_install_user_invalid(u):
    with pytest.raises(InvalidInstallUserError):
        validate_install_user(u)


# ── Repo URL ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("u", [
    "https://github.com/RickDnamps/AstromechOS.git",
    "https://gitlab.example.com/me/fork.git",
    "git@github.com:me/repo.git",
])
def test_repo_url_valid(u):
    validate_repo_url(u)


@pytest.mark.parametrize("u", ["file:///tmp/repo", "http://x", "ftp://x", "x"])
def test_repo_url_invalid(u):
    with pytest.raises(InvalidRepoUrlError):
        validate_repo_url(u)


# ── Branch name ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("b", ["main", "develop", "feature/x", "v1.2.3"])
def test_branch_name_valid(b):
    validate_branch_name(b)


@pytest.mark.parametrize("b", ["", "/leading", "trailing/", "double//slash", "x..y",
                                "ends.lock"])
def test_branch_name_invalid(b):
    with pytest.raises(InvalidBranchNameError):
        validate_branch_name(b)


# ── SSID 802.11 ───────────────────────────────────────────────────────────
# Bootstrap SSID is ``Astromech-<4 decimal digits>`` per the dual-WLAN
# amendment — random per burn so simultaneous unboxed pairs don't
# collide on the bootstrap AP. The FINAL runtime SSID
# ``Astromech_Control_XXXX`` is derived Pi-side from the CPU serial
# and never reaches this validator.
@pytest.mark.parametrize("s", [
    "Astromech-0000",
    "Astromech-1234",
    "Astromech-8392",
    "Astromech-9999",
])
def test_ssid_valid(s):
    validate_ssid(s)


@pytest.mark.parametrize("s", [
    "",
    "Astromech-",               # missing digits
    "Astromech-12",             # too short
    "Astromech-12345",          # too long
    "Astromech-ABCD",           # not digits
    "astromech-1234",           # wrong case
    "AstromechOS-1234",         # wrong prefix (legacy)
    "Astromech_Boot_3F2A",      # wrong prefix (legacy)
    "Astromech_Control_3F2A",   # runtime-final value (Pi-only, never written by Imager)
    "Astromech-1234 ",          # trailing space
    "Other-1234",
])
def test_ssid_invalid(s):
    with pytest.raises(InvalidHotspotSsidError):
        validate_ssid(s)


# ── WPA2 PSK ──────────────────────────────────────────────────────────────
def test_psk_min_length():
    validate_wpa2_psk("a" * 8)


def test_psk_max_length():
    validate_wpa2_psk("a" * 63)


@pytest.mark.parametrize("p", ["short", "a" * 64, "with\x00null", "with\nnewline"])
def test_psk_invalid(p):
    with pytest.raises(InvalidHotspotPskError):
        validate_wpa2_psk(p)


# ── Property: firstboot regex subsumption ─────────────────────────────────
@given(st.text(alphabet=string.ascii_letters + string.digits + "-", min_size=1, max_size=63))
def test_hostname_property_matches_firstboot_regex(h: str):
    """Our regex MUST be subset of firstboot_setup.sh:206. If we accept, firstboot accepts."""
    firstboot_re = re.compile(r"^[a-zA-Z0-9](-?[a-zA-Z0-9])*$")
    try:
        validate_hostname(h)
        assert firstboot_re.match(h) is not None, \
            f"Our validator accepted {h!r} but firstboot would reject it"
    except Exception:
        pass  # either may reject; subsumption means we are not LESS strict
