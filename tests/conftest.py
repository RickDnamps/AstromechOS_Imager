"""Shared pytest fixtures."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect %APPDATA% to tmp_path so tests don't pollute the user profile."""
    appdata = tmp_path / "AppData"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    return appdata


@pytest.fixture
def fixed_iso_time(monkeypatch: pytest.MonkeyPatch) -> str:
    """Freeze the wall clock so golden snapshots stay stable."""
    iso = "2026-05-29T02:15:00Z"
    monkeypatch.setattr("astromechos_imager.core.models._utc_iso_now", lambda: iso)
    return iso


@pytest.fixture
def fake_boot_partition():
    """In-memory BootPartition impl for testing renderers + FirstbootBundle."""

    class _Fake:
        def __init__(self):
            self.files: dict[str, bytes] = {}
            self.dirs: set[str] = {"/"}

        def write_bytes(self, p, d):
            parent = "/" + "/".join(p.lstrip("/").split("/")[:-1])
            parent = parent.rstrip("/") or "/"
            if parent not in self.dirs:
                raise FileNotFoundError(f"parent {parent} missing")
            self.files[p] = d

        def read_bytes(self, p):
            return self.files[p]

        def mkdir(self, p):
            self.dirs.add(p)

        def exists(self, p):
            return p in self.files or p in self.dirs

        def close(self):
            pass

    return _Fake()
