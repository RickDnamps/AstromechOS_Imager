"""Per design spec §6.5. Regex aligned with firstboot_setup.sh:206 and IEEE 802.11i."""
from __future__ import annotations

import re

from astromechos_imager.core.errors import (
    InvalidHostnameError,  # re-exported for FirstbootConfig collision check
    InvalidAuthorizedKeysError,
    InvalidInstallUserError,
    InvalidRepoUrlError,
    InvalidBranchNameError,
    InvalidHotspotSsidError,
    InvalidHotspotPskError,
    InvalidWifiSsidError,
    InvalidWifiPskError,
)


# Strict RFC 1123, copy of firstboot_setup.sh:206
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9](?:-?[a-zA-Z0-9])*$")

OPENSSH_PUBKEY_RE = re.compile(
    r"^(?:ssh-(?:rsa|ed25519|dss)"
    r"|ecdsa-sha2-nistp(?:256|384|521)"
    r"|sk-(?:ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)"
    r"\s+[A-Za-z0-9+/=.]+(?:\s+.+)?$"
)

_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

_REPO_URL_RE = re.compile(
    r"^(?:https://[^\s]+|git@[^\s:]+:[^\s]+)$"
)

# Simplified git refname rules
_BRANCH_RE = re.compile(r"^(?!.*\.\.)(?!/)(?!.*//)[A-Za-z0-9._/-]+$")

_SSID_RE = re.compile(r"^Astromech_Boot_[0-9A-F]{4,8}$")


def validate_hostname(h: str) -> None:
    if not h or len(h) > 63 or not _HOSTNAME_RE.match(h):
        raise InvalidHostnameError(h)


def validate_authorized_keys(keys: list[str]) -> None:
    if not keys:
        raise InvalidAuthorizedKeysError("at least one key required")
    for k in keys:
        if not OPENSSH_PUBKEY_RE.match(k.strip()):
            raise InvalidAuthorizedKeysError(f"not an OpenSSH pubkey: {k!r}")


def validate_install_user(u: str) -> None:
    if not _USER_RE.match(u):
        raise InvalidInstallUserError(u)


def validate_repo_url(u: str) -> None:
    if not _REPO_URL_RE.match(u):
        raise InvalidRepoUrlError(u)


def validate_branch_name(b: str) -> None:
    if not b or b.endswith(".lock") or b.endswith("/") or not _BRANCH_RE.match(b):
        raise InvalidBranchNameError(b)


def validate_ssid(s: str) -> None:
    if not _SSID_RE.match(s) or len(s.encode("utf-8")) > 32:
        raise InvalidHotspotSsidError(s)


def validate_wpa2_psk(p: str) -> None:
    if not (8 <= len(p) <= 63) or not p.isascii() or not p.isprintable():
        # Never echo the actual PSK in the message
        raise InvalidHotspotPskError("<redacted: invalid WPA2 PSK>")


def validate_wifi_ssid(s: str) -> None:
    """Relaxed WiFi SSID validator for home/arbitrary networks.

    IEEE 802.11 allows any 1–32 byte UTF-8 sequence (non-empty after strip).
    Distinct from validate_ssid() which enforces the AstromechOS hotspot pattern.
    """
    stripped = s.strip()
    if not stripped:
        raise InvalidWifiSsidError("WiFi SSID must be non-empty after stripping whitespace")
    if len(s.encode("utf-8")) > 32:
        raise InvalidWifiSsidError(
            f"WiFi SSID must be ≤ 32 UTF-8 bytes (got {len(s.encode('utf-8'))})"
        )


def validate_wifi_psk(p: str) -> None:
    """WPA2-PSK passphrase validator for home WiFi credentials.

    Accepts 8–63 ASCII printable characters, matching WPA2-PSK constraints.
    """
    if not (8 <= len(p) <= 63) or not p.isascii() or not p.isprintable():
        raise InvalidWifiPskError("<redacted: invalid WiFi WPA2 PSK>")
