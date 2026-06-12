"""Core data model. Per design spec §6.1.

Validation methods are wired in at __post_init__ time, but the actual
validators live in core/validators.py to keep them reusable from the UI
preflight pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path


def _utc_iso_now() -> str:
    """Wall clock indirection — monkeypatched in tests for deterministic snapshots."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Role(Enum):
    MASTER = "master"
    SLAVE = "slave"


@dataclass(frozen=True)
class HotspotBootstrap:
    ssid: str
    password: str


@dataclass(frozen=True)
class LinuxAccount:
    """Cold-modification target for the Golden Image's UID-1000 Linux user.

    The Imager renames UID-1000 to ``username`` and sets its password to
    ``cleartext_password`` (hashed as ``crypt_sha512`` for /etc/shadow).
    All three fields populated by ``generate_linux_account()``.
    """

    username: str            # New POSIX login replacing the Golden Image's UID-1000 name
    cleartext_password: str  # ~16 chars from secrets.token_urlsafe(12) — shown once to operator
    crypt_sha512: str        # $6$<salt>$<hash> written directly to /etc/shadow (Phase 5.5)


@dataclass(frozen=True)
class Ed25519Pair:
    private_openssh: bytes
    public_openssh: bytes


@dataclass(frozen=True)
class DiskRef:
    """A removable drive candidate. Populated by platform/windows.py::enumerate_drives()."""
    physical_drive_id: int       # e.g. 2 → \\.\PHYSICALDRIVE2
    device_path: str             # full Win32 path
    drive_letters: tuple[str, ...]  # e.g. ("E",) — may be empty if no FS recognised yet
    size_bytes: int
    model: str
    serial: str
    # Raw WMI MediaType ("Removable Media", "Fixed hard disk media", …).
    # "fixed" + USB usually means an external SSD, not an SD card — consumers
    # treat those as suspect (never auto-touched, explicit confirmation).
    media_type: str = ""

    @property
    def is_suspect_fixed(self) -> bool:
        """USB-attached FIXED media (external SSD/HDD) — eligible but never
        auto-selected and never auto-dismounted."""
        return "fixed" in self.media_type.lower()


@dataclass(frozen=True)
class ImageRef:
    """A user-selected source image. Format-detected by core/imagesource.py."""
    path: Path
    detected_format: str         # "raw" | "xz" | "gz" | "zip"
    uncompressed_size: int | None


from astromechos_imager.core import validators as _v  # noqa: E402


@dataclass(frozen=True)
class FirstbootConfig:
    """Per design spec §6.1.

    Validation runs in __post_init__ — the same validators are also used by the
    UI's preflight pass so users get immediate feedback in step 4.
    """
    authorized_keys: list[str]
    install_user: str = "pi"
    repo_url: str | None = None
    repo_branch: str = "main"
    hostname_master: str = "astromech-master"
    hostname_slave: str = "astromech-slave"
    hw_layout_master: Path | None = None
    hw_layout_slave: Path | None = None
    hotspot_bootstrap: HotspotBootstrap | None = None
    # Auto-managed by orchestrator — empty defaults exist for unit tests only.
    imager_version: str = ""
    flashed_at_iso: str = ""
    # Optional home WiFi for wlan1 dongle — Phase 8.10
    wifi_ssid: str | None = None   # home WiFi SSID for wlan1 dongle (optional)
    wifi_psk: str | None = None    # corresponding WPA2-PSK

    def __post_init__(self) -> None:
        _v.validate_authorized_keys(self.authorized_keys)
        _v.validate_install_user(self.install_user)
        _v.validate_hostname(self.hostname_master)
        _v.validate_hostname(self.hostname_slave)
        if self.hostname_master == self.hostname_slave:
            raise _v.InvalidHostnameError(
                "master and slave hostnames must differ"
            )
        if self.repo_url is not None:
            _v.validate_repo_url(self.repo_url)
            _v.validate_branch_name(self.repo_branch)
        if self.hotspot_bootstrap is not None:
            _v.validate_ssid(self.hotspot_bootstrap.ssid)
            _v.validate_wpa2_psk(self.hotspot_bootstrap.password)
        # WiFi creds: both provided together or both absent — half-config is rejected
        ssid_present = bool(self.wifi_ssid)
        psk_present = bool(self.wifi_psk)
        if ssid_present and psk_present:
            # Full config: validate both
            _v.validate_wifi_ssid(self.wifi_ssid)  # type: ignore[arg-type]
            _v.validate_wifi_psk(self.wifi_psk)    # type: ignore[arg-type]
        elif ssid_present and not psk_present:
            # SSID without PSK — half-config
            raise _v.InvalidWifiSsidError(
                "WiFi SSID and PSK must be provided together"
            )
        elif not ssid_present and psk_present:
            # PSK without SSID — half-config
            raise _v.InvalidWifiSsidError(
                "WiFi SSID and PSK must be provided together"
            )
        # Both empty/None: fully optional — skip
