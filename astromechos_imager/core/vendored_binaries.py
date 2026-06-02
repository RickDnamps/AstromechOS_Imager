"""Locate vendored native binaries bundled with AstromechOS Imager.

Currently the only vendored binary is ``astro_flash.dll`` (the native
shell-quiet helper). Frozen (PyInstaller) builds resolve it from
``<sys._MEIPASS>/vendor``; dev runs from ``<project_root>/vendor``.
"""
from __future__ import annotations

import sys
from pathlib import Path


def vendor_root() -> Path:
    """Return the directory containing the vendored binaries."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "vendor"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2] / "vendor"
