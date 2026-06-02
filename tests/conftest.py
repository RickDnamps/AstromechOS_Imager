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


@pytest.fixture
def fake_platform_io(tmp_path):
    """Dict-backed PlatformIO impl. Each physical_drive_id maps to a sparse file."""
    from astromechos_imager.core.models import DiskRef

    class _FakeRawDevice:
        sector_size = 512

        def __init__(self, path, size):
            self._path = path
            self.size_bytes = size
            self._fh = open(path, "r+b")
            self._h = 0xF000  # mimic _Win32RawDevice's handle attr (eject/sync probe it)

        def write(self, offset, data):
            self._fh.seek(offset)
            self._fh.write(data)
            return len(data)

        def read(self, offset, length):
            self._fh.seek(offset)
            return self._fh.read(length)

        def flush(self):
            self._fh.flush()

        def close(self):
            self._fh.close()

    class _Fake:
        def __init__(self):
            self.drives: dict[int, DiskRef] = {}
            self.handles: list[int] = []
            self._next_h = 1000

        def add_drive(self, phys_id: int, size: int = 32 << 30, model="Test SD"):
            path = tmp_path / f"sparse_{phys_id}.img"
            path.touch()
            os.truncate(path, size)
            self.drives[phys_id] = DiskRef(
                physical_drive_id=phys_id,
                device_path=f"\\\\.\\PHYSICALDRIVE{phys_id}",
                drive_letters=(),
                size_bytes=size,
                model=model,
                serial=f"TEST-{phys_id}",
            )
            return path

        def enumerate_removable_drives(self):
            return list(self.drives.values())

        def lock_and_dismount(self, letters, physical_drive_id=None):
            self._next_h += 1
            return [self._next_h + i for i, _ in enumerate(letters)]

        def open_raw_device(self, phys_id):
            path = tmp_path / f"sparse_{phys_id}.img"
            return _FakeRawDevice(path, self.drives[phys_id].size_bytes)

        def close_handle(self, h):
            pass

        def update_disk_properties(self, h):
            pass

        def eject_media(self, h):
            pass

        def finalize_eject(self, physical_drive_id):
            pass

    return _Fake()
