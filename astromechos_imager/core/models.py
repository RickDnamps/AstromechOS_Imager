"""Core data model. Per design spec §6.1.

Validation methods are wired in at __post_init__ time, but the actual
validators live in core/validators.py to keep them reusable from the UI
preflight pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


def _utc_iso_now() -> str:
    """Wall clock indirection — monkeypatched in tests for deterministic snapshots."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Role(Enum):
    MASTER = "master"
    SLAVE = "slave"


@dataclass(frozen=True)
class HotspotBootstrap:
    ssid: str
    password: str


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


@dataclass(frozen=True)
class ImageRef:
    """A user-selected source image. Format-detected by core/imagesource.py."""
    path: Path
    detected_format: str         # "raw" | "xz" | "gz" | "zip"
    uncompressed_size: int | None
