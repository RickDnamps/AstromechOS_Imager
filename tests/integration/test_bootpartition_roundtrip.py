"""Integration tests for PyFatFsBootPartition against a real FAT32 sparse image.

These tests use pyfatfs to format and read/write a FAT32 partition inside a
temporary sparse file.  They are marked ``integration`` and skipped gracefully
if pyfatfs cannot format-on-demand (e.g. partition too small for the chosen
FAT variant's cluster geometry).

The α (drive-letter) path cannot be tested without a real Windows drive-mount
event, so it is covered only by the manual E2E test plan.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECTOR = 512
_START_LBA = 2048
_BOOT_MB = 64         # must be large enough for FAT32 cluster geometry
_TOTAL_MB = 128       # total sparse image size


def _stub_pkg_resources() -> None:
    """Ensure pkg_resources is available (needed by pyfatfs dep 'fs')."""
    if "pkg_resources" not in sys.modules:
        import types

        stub = types.ModuleType("pkg_resources")
        stub.declare_namespace = lambda _name: None  # type: ignore[attr-defined]
        sys.modules["pkg_resources"] = stub


def _format_fat32_partition(img_path: Path, offset_bytes: int, size_bytes: int) -> None:
    """Format a slice of *img_path* as FAT32 using PyFat.mkfs().

    PyFat.mkfs() writes the FAT32 boot sector and FATs at *offset_bytes*
    within the file, spanning *size_bytes*.  The file must already exist with
    sufficient length.
    """
    _stub_pkg_resources()
    from pyfatfs import PyFat as PyFatMod  # noqa: PLC0415

    pf = PyFatMod.PyFat(offset=offset_bytes)
    try:
        pf.mkfs(
            str(img_path),
            PyFatMod.PyFat.FAT_TYPE_FAT32,
            size=size_bytes,
        )
    finally:
        try:
            pf.close()
        except Exception:
            pass


def _make_fat32_image(path: Path) -> tuple[int, int]:
    """Build a sparse MBR disk image with one FAT32 partition formatted via pyfatfs.

    Returns ``(offset_bytes, size_bytes)`` of the partition.
    """
    total_bytes = _TOTAL_MB * 1024 * 1024
    size_lba = (_BOOT_MB * 1024 * 1024) // _SECTOR
    offset_bytes = _START_LBA * _SECTOR
    size_bytes = size_lba * _SECTOR

    # Create a sparse file by seeking to the end and writing one byte
    with path.open("wb") as fh:
        fh.seek(total_bytes - 1)
        fh.write(b"\x00")

    # Write a minimal MBR
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    entry = bytearray(16)
    entry[4] = 0x0C  # FAT32 LBA
    struct.pack_into("<I", entry, 8, _START_LBA)
    struct.pack_into("<I", entry, 12, size_lba)
    mbr[446:462] = bytes(entry)
    with path.open("r+b") as fh:
        fh.write(bytes(mbr))

    # Format the partition region as FAT32
    _format_fat32_partition(path, offset_bytes, size_bytes)

    return offset_bytes, size_bytes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fat32_image(tmp_path: Path):
    """Create a temporary FAT32 sparse image.  Skip if formatting fails."""
    img = tmp_path / "fake_sd.img"
    try:
        offset, size = _make_fat32_image(img)
    except Exception as exc:
        pytest.skip(f"pyfatfs cannot format-on-demand in this environment: {exc}")
    return img, offset, size


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pyfatfs_roundtrip(fat32_image):
    """β path: write + read back files via PyFatFsBootPartition on a FAT32 image."""
    from astromechos_imager.core.bootpartition import (  # noqa: PLC0415
        BootPartitionLayout,
        PyFatFsBootPartition,
        find_first_fat32_partition,
    )

    img_path, _offset, _size = fat32_image

    # Parse MBR to get the layout
    mbr_bytes = img_path.read_bytes()[:512]
    layout = find_first_fat32_partition(mbr_bytes)

    bp = PyFatFsBootPartition(str(img_path), layout)
    try:
        # mkdir + write
        bp.mkdir("/astromech_secrets")
        payload = b'{"role":"master","hostname":"astromech-master"}'
        bp.write_bytes("/astromech_secrets/init_config.json", payload)
        bp.write_bytes("/ASTROMECH_FIRSTBOOT_READY", b"")

        # exists checks
        assert bp.exists("/astromech_secrets/init_config.json")
        assert bp.exists("/ASTROMECH_FIRSTBOOT_READY")
        assert not bp.exists("/nonexistent")

        # read back
        assert bp.read_bytes("/astromech_secrets/init_config.json") == payload
        assert bp.read_bytes("/ASTROMECH_FIRSTBOOT_READY") == b""
    finally:
        bp.close()


def test_pyfatfs_nested_directories(fat32_image):
    """β path: nested directory creation and file write."""
    from astromechos_imager.core.bootpartition import (  # noqa: PLC0415
        BootPartitionLayout,
        PyFatFsBootPartition,
        find_first_fat32_partition,
    )

    img_path, _offset, _size = fat32_image
    mbr_bytes = img_path.read_bytes()[:512]
    layout = find_first_fat32_partition(mbr_bytes)

    bp = PyFatFsBootPartition(str(img_path), layout)
    try:
        bp.mkdir("/astromech_secrets")
        bp.write_bytes("/astromech_secrets/id_ed25519", b"PRIVATE_KEY_DATA")
        bp.write_bytes("/astromech_secrets/id_ed25519.pub", b"ssh-ed25519 AAAA pub\n")
        bp.write_bytes("/astromech_secrets/authorized_keys", b"ssh-ed25519 AAAA user@host\n")

        assert bp.exists("/astromech_secrets/id_ed25519")
        assert bp.exists("/astromech_secrets/id_ed25519.pub")
        assert bp.read_bytes("/astromech_secrets/id_ed25519") == b"PRIVATE_KEY_DATA"
    finally:
        bp.close()


def test_pyfatfs_overwrite(fat32_image):
    """β path: overwriting an existing file replaces its content."""
    from astromechos_imager.core.bootpartition import (  # noqa: PLC0415
        BootPartitionLayout,
        PyFatFsBootPartition,
        find_first_fat32_partition,
    )

    img_path, _offset, _size = fat32_image
    mbr_bytes = img_path.read_bytes()[:512]
    layout = find_first_fat32_partition(mbr_bytes)

    bp = PyFatFsBootPartition(str(img_path), layout)
    try:
        bp.write_bytes("/marker.txt", b"original")
        bp.write_bytes("/marker.txt", b"updated")
        assert bp.read_bytes("/marker.txt") == b"updated"
    finally:
        bp.close()


def test_pyfatfs_mounts_from_layout(fat32_image):
    """The layout returned by find_first_fat32_partition drives the correct mount offset."""
    from astromechos_imager.core.bootpartition import (  # noqa: PLC0415
        BootPartitionLayout,
        PyFatFsBootPartition,
        find_first_fat32_partition,
    )

    img_path, expected_offset, _size = fat32_image
    mbr_bytes = img_path.read_bytes()[:512]
    layout = find_first_fat32_partition(mbr_bytes)

    assert layout.offset == expected_offset
    assert layout.partition_type == 0x0C

    bp = PyFatFsBootPartition(str(img_path), layout)
    try:
        bp.write_bytes("/probe.txt", b"layout-ok")
        assert bp.read_bytes("/probe.txt") == b"layout-ok"
    finally:
        bp.close()
