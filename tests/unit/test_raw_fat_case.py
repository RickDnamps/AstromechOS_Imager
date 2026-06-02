"""RawFatBootPartition resolves FAT names case-insensitively.

Pi OS stores cmdline.txt as a short 8.3 entry; pyfatfs returns it uppercased
('CMDLINE.TXT') and looks up case-sensitively, so '/cmdline.txt' must still be
found / read / overwritten (no duplicate entry).
"""
from __future__ import annotations

import pytest

from astromechos_imager.core.raw_fat_partition import RawFatBootPartition


class _FakePyFat:
    """Minimal pyfatfs stand-in storing names with their on-disk case."""

    def __init__(self, files):
        self.files = dict(files)   # stored-name -> bytes (root level)

    def exists(self, path):
        return path == "/" or path.lstrip("/") in self.files

    def listdir(self, parent):
        assert parent == "/"
        return list(self.files)

    def readbytes(self, path):
        return self.files[path.lstrip("/")]

    def writebytes(self, path, data):
        self.files[path.lstrip("/")] = data


def _bp(files):
    bp = RawFatBootPartition.__new__(RawFatBootPartition)
    bp._pfs = _FakePyFat(files)
    bp._closed = False
    return bp


def test_read_finds_uppercased_short_name():
    bp = _bp({"CMDLINE.TXT": b"console=tty1 rootwait\n"})
    assert bp.exists("/cmdline.txt")
    assert bp.read_bytes("/cmdline.txt") == b"console=tty1 rootwait\n"


def test_write_overwrites_existing_entry_no_duplicate():
    bp = _bp({"CMDLINE.TXT": b"old\n"})
    bp.write_bytes("/cmdline.txt", b"new\n")
    # Overwrote CMDLINE.TXT in place — no second 'cmdline.txt' entry created.
    assert bp._pfs.files == {"CMDLINE.TXT": b"new\n"}


def test_write_new_file_uses_requested_path():
    bp = _bp({"CMDLINE.TXT": b"x"})
    bp.write_bytes("/firstrun.sh", b"#!/bin/sh\n")
    assert bp._pfs.files["firstrun.sh"] == b"#!/bin/sh\n"


def test_missing_file_raises_filenotfound():
    bp = _bp({"CONFIG.TXT": b"x"})
    assert not bp.exists("/cmdline.txt")
    with pytest.raises(FileNotFoundError):
        bp.read_bytes("/cmdline.txt")
