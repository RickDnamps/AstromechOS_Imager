"""Integration tests for Ext4DebugfsBackend via WSL debugfs.

Skipped automatically if WSL is not available or the fixture image is missing.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from astromechos_imager.core.rootfs import Ext4DebugfsBackend, _win_to_wsl_path

FIXTURE = Path("tests/poc/fixture.ext4.img").absolute()

pytestmark = pytest.mark.integration

# Skip the entire module at collection time if WSL or fixture unavailable.
if not FIXTURE.exists() or shutil.which("wsl") is None:
    pytest.skip(
        "WSL or ext4 fixture not available",
        allow_module_level=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────


def _make_backend(image: Path, offset: int = 0) -> Ext4DebugfsBackend:
    return Ext4DebugfsBackend(
        image_path=_win_to_wsl_path(image),
        offset_bytes=offset,
        debugfs_exe=Path("/usr/sbin/debugfs"),
        e2fsck_exe=Path("/usr/sbin/e2fsck"),
        invoker=["wsl"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pure-Python helper test (no WSL needed)
# ─────────────────────────────────────────────────────────────────────────────


def test_win_to_wsl_path() -> None:
    p = Path("J:/R2-D2_Build/AstroMechOS_Imager/tests/poc/fixture.ext4.img")
    result = _win_to_wsl_path(p)
    assert result == "/mnt/j/R2-D2_Build/AstroMechOS_Imager/tests/poc/fixture.ext4.img"


# ─────────────────────────────────────────────────────────────────────────────
# Backend integration tests
# ─────────────────────────────────────────────────────────────────────────────


def test_read_bytes(tmp_path: Path) -> None:
    """read_bytes('/etc/passwd') should contain root and a UID-1000 entry."""
    fix = tmp_path / "fixture.img"
    shutil.copy(FIXTURE, fix)
    bk = _make_backend(fix)
    try:
        data = bk.read_bytes("/etc/passwd")
        assert b"root:x:0:0" in data
        assert b"1000:1000" in data  # UID-1000 user
    finally:
        bk.close()


def test_write_bytes_replaces_content(tmp_path: Path) -> None:
    """write_bytes should atomically replace a file's content."""
    fix = tmp_path / "fixture.img"
    shutil.copy(FIXTURE, fix)
    bk = _make_backend(fix)
    try:
        bk.write_bytes(
            "/etc/passwd",
            b"root:x:0:0:root:/root:/bin/bash\n"
            b"artoo:x:1000:1000:,,,:/home/artoo:/bin/bash\n",
        )
        out = bk.read_bytes("/etc/passwd")
        assert b"artoo:x:1000" in out
        assert b"pi:x:1000" not in out
    finally:
        bk.close()


def test_rename_preserves_inode(tmp_path: Path) -> None:
    """rename() via link+unlink should keep file accessible under the new name."""
    fix = tmp_path / "fixture.img"
    shutil.copy(FIXTURE, fix)
    bk = _make_backend(fix)
    try:
        # Be defensive about starting state — fixture may have /home/pi OR /home/artoo
        try:
            bk.read_bytes("/home/pi/welcome.txt")
            # /home/pi exists → rename to /home/artoo
            bk.rename("/home/pi", "/home/artoo")
        except Exception:
            # /home/pi missing — assume /home/artoo is current; rename back then forward
            bk.rename("/home/artoo", "/home/pi")
            bk.rename("/home/pi", "/home/artoo")

        content = bk.read_bytes("/home/artoo/welcome.txt")
        assert content.strip() == b"hello from pi"
    finally:
        bk.close()


def test_fsck_clean(tmp_path: Path) -> None:
    """A freshly copied fixture should pass e2fsck without errors."""
    fix = tmp_path / "fixture.img"
    shutil.copy(FIXTURE, fix)
    bk = _make_backend(fix)
    try:
        assert bk.fsck_clean() is True
    finally:
        bk.close()
