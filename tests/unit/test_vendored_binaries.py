"""Unit tests for astromechos_imager.core.vendored_binaries.

These tests verify the resolver logic only — no actual debugfs.exe or
e2fsck.exe is required to be present.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from astromechos_imager.core.vendored_binaries import (
    debugfs_exe,
    e2fsck_exe,
    vendor_root,
)


# ---------------------------------------------------------------------------
# vendor_root() — dev mode
# ---------------------------------------------------------------------------


class TestVendorRootDevMode:
    def test_returns_vendor_subdir_of_project_root(self) -> None:
        """In dev mode the resolver must walk up to the project root."""
        # Ensure we're not in frozen mode
        with patch.object(sys, "frozen", False, create=True):
            root = vendor_root()
        assert root.name == "vendor"
        # The parent of vendor/ must be the project root (two levels above core/)
        # i.e. .../astromechos_imager/core/ -> ../../ == project root
        assert root.parent.name != "astromechos_imager"  # not inside the package

    def test_dev_vendor_root_is_absolute(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            root = vendor_root()
        assert root.is_absolute()

    def test_dev_vendor_root_ends_with_vendor(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            root = vendor_root()
        assert root.name == "vendor"


# ---------------------------------------------------------------------------
# vendor_root() — frozen mode (simulated)
# ---------------------------------------------------------------------------


class TestVendorRootFrozenMode:
    def test_frozen_returns_meipass_vendor(self, tmp_path: Path) -> None:
        fake_meipass = str(tmp_path / "fake-meipass")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", fake_meipass, create=True),
        ):
            root = vendor_root()
        assert root == Path(fake_meipass) / "vendor"

    def test_frozen_path_is_absolute(self, tmp_path: Path) -> None:
        fake_meipass = str(tmp_path / "_MEIPASS_abs")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", fake_meipass, create=True),
        ):
            root = vendor_root()
        assert root.is_absolute()


# ---------------------------------------------------------------------------
# debugfs_exe() — missing binary raises RuntimeError
# ---------------------------------------------------------------------------


class TestDebugfsExe:
    def test_raises_runtimeerror_when_missing(self, tmp_path: Path) -> None:
        """debugfs_exe() must raise RuntimeError with a helpful message when
        debugfs.exe is absent from the vendor directory."""
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                debugfs_exe()
        msg = str(exc_info.value)
        assert "debugfs.exe" in msg
        assert "vendor" in msg.lower() or "README" in msg

    def test_returns_path_when_present(self, tmp_path: Path) -> None:
        """debugfs_exe() must return the concrete Path when the file exists."""
        vendor_dir = tmp_path / "vendor"
        vendor_dir.mkdir()
        fake_exe = vendor_dir / "debugfs.exe"
        fake_exe.touch()
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            result = debugfs_exe()
        assert result == fake_exe
        assert result.is_file()


# ---------------------------------------------------------------------------
# e2fsck_exe() — missing binary raises RuntimeError
# ---------------------------------------------------------------------------


class TestE2fsckExe:
    def test_raises_runtimeerror_when_missing(self, tmp_path: Path) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                e2fsck_exe()
        msg = str(exc_info.value)
        assert "e2fsck.exe" in msg

    def test_returns_path_when_present(self, tmp_path: Path) -> None:
        vendor_dir = tmp_path / "vendor"
        vendor_dir.mkdir()
        fake_exe = vendor_dir / "e2fsck.exe"
        fake_exe.touch()
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            result = e2fsck_exe()
        assert result == fake_exe
        assert result.is_file()

    def test_error_message_mentions_readme(self, tmp_path: Path) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                e2fsck_exe()
        assert "README" in str(exc_info.value)
