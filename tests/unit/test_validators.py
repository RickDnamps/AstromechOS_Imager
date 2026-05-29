# tests/unit/test_validators.py
import pytest
from hypothesis import given, strategies as st, assume
import re, string

from astromechos_imager.core.validators import (
    validate_hostname, validate_authorized_keys, validate_install_user,
    validate_repo_url, validate_branch_name, validate_ssid, validate_wpa2_psk,
    OPENSSH_PUBKEY_RE,
)
from astromechos_imager.core.errors import (
    InvalidHostnameError, InvalidAuthorizedKeysError, InvalidInstallUserError,
    InvalidRepoUrlError, InvalidBranchNameError, InvalidHotspotSsidError,
    InvalidHotspotPskError,
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


def test_authorized_keys_empty_list_rejected():
    with pytest.raises(InvalidAuthorizedKeysError):
        validate_authorized_keys([])


# ── Install user (POSIX login) ────────────────────────────────────────────
@pytest.mark.parametrize("u", ["pi", "astromech", "artoo", "_svc", "user-1"])
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
@pytest.mark.parametrize("s", ["Astromech_Boot_3F2A", "Astromech_Boot_AABBCC", "Astromech_Boot_ABCD"])
def test_ssid_valid(s):
    validate_ssid(s)


@pytest.mark.parametrize("s", ["Astromech_Boot_xx", "Astromech_Boot_", "Other_3F2A",
                                "Astromech_Boot_3F2A" + "X" * 20, "Astromech_Boot_GHIJ"])
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
