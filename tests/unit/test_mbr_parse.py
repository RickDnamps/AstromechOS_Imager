"""Unit tests for MBR parsing (find_first_fat32_partition)."""
from __future__ import annotations

import struct

import pytest

from astromechos_imager.core.bootpartition import BootPartitionLayout, find_first_fat32_partition
from astromechos_imager.core.errors import BootPartitionMountError


def _make_mbr(
    ptype: int = 0x0C,
    lba_start: int = 8192,
    lba_size: int = 1024 * 1024,
    entry_index: int = 0,
) -> bytes:
    """Build a minimal valid MBR with one partition entry."""
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    offset = 446 + entry_index * 16
    e = bytearray(16)
    e[0] = 0x00  # boot indicator (non-bootable)
    e[4] = ptype
    struct.pack_into("<I", e, 8, lba_start)
    struct.pack_into("<I", e, 12, lba_size)
    mbr[offset : offset + 16] = bytes(e)
    return bytes(mbr)


def test_typical_pi_os_layout():
    """First 512 bytes of a typical Pi OS image: MBR with one FAT32 (type 0x0C)
    partition starting at sector 8192, length 1048576 sectors (512 MB)."""
    mbr = _make_mbr(ptype=0x0C, lba_start=8192, lba_size=1024 * 1024)
    layout = find_first_fat32_partition(mbr)
    assert isinstance(layout, BootPartitionLayout)
    assert layout.offset == 8192 * 512
    assert layout.size == 1024 * 1024 * 512
    assert layout.partition_type == 0x0C


def test_fat32_type_0x0b():
    """0x0B is also FAT32 (CHS-addressed)."""
    mbr = _make_mbr(ptype=0x0B, lba_start=2048, lba_size=524288)
    layout = find_first_fat32_partition(mbr)
    assert layout.partition_type == 0x0B
    assert layout.offset == 2048 * 512
    assert layout.size == 524288 * 512


def test_fat16_type_0x06():
    """0x06 (FAT16 large) is also accepted."""
    mbr = _make_mbr(ptype=0x06, lba_start=63, lba_size=16065)
    layout = find_first_fat32_partition(mbr)
    assert layout.partition_type == 0x06


def test_fat16_type_0x0e():
    """0x0E (FAT16 LBA) is accepted."""
    mbr = _make_mbr(ptype=0x0E, lba_start=2048, lba_size=65536)
    layout = find_first_fat32_partition(mbr)
    assert layout.partition_type == 0x0E


def test_returns_first_matching_partition():
    """When multiple FAT entries are present, the first one wins."""
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    # Entry 0: Linux (0x83) — not FAT, skip
    struct.pack_into("<I", bytearray(mbr[446:462]), 8, 2048)  # no effect; zero ptype

    # Entry 1: FAT32 (0x0C) — first FAT hit
    e1 = bytearray(16)
    e1[4] = 0x0C
    struct.pack_into("<I", e1, 8, 4096)
    struct.pack_into("<I", e1, 12, 131072)
    mbr[462:478] = bytes(e1)

    # Entry 2: FAT32 (0x0B) — second FAT hit (should be ignored)
    e2 = bytearray(16)
    e2[4] = 0x0B
    struct.pack_into("<I", e2, 8, 8192)
    struct.pack_into("<I", e2, 12, 262144)
    mbr[478:494] = bytes(e2)

    layout = find_first_fat32_partition(bytes(mbr))
    assert layout.offset == 4096 * 512
    assert layout.partition_type == 0x0C


def test_empty_mbr_raises():
    """All-zero MBR with no signature → BootPartitionMountError."""
    with pytest.raises(BootPartitionMountError, match="Invalid MBR signature"):
        find_first_fat32_partition(b"\x00" * 512)


def test_wrong_signature_raises():
    """Wrong MBR signature → BootPartitionMountError."""
    mbr = bytearray(512)
    mbr[510:512] = b"\xAA\x55"  # reversed
    with pytest.raises(BootPartitionMountError, match="Invalid MBR signature"):
        find_first_fat32_partition(bytes(mbr))


def test_too_short_raises():
    """Less than 512 bytes → BootPartitionMountError."""
    with pytest.raises(BootPartitionMountError):
        find_first_fat32_partition(b"\x00" * 100)


def test_no_fat_partition_raises():
    """Valid MBR signature but no FAT entries → BootPartitionMountError."""
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    # Entry 0: Linux ext4 (0x83)
    mbr[446 + 4] = 0x83
    struct.pack_into("<I", bytearray(mbr[446:462]), 8, 2048)
    with pytest.raises(BootPartitionMountError, match="No FAT32 partition"):
        find_first_fat32_partition(bytes(mbr))


def test_zero_size_partition_skipped():
    """A FAT entry with lba_size=0 (deleted/empty) is skipped."""
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    # Entry 0: FAT32 but size=0 (should be skipped)
    e0 = bytearray(16)
    e0[4] = 0x0C
    struct.pack_into("<I", e0, 8, 2048)
    struct.pack_into("<I", e0, 12, 0)  # zero size
    mbr[446:462] = bytes(e0)
    # Entry 1: FAT32, valid
    e1 = bytearray(16)
    e1[4] = 0x0B
    struct.pack_into("<I", e1, 8, 4096)
    struct.pack_into("<I", e1, 12, 65536)
    mbr[462:478] = bytes(e1)
    layout = find_first_fat32_partition(bytes(mbr))
    assert layout.offset == 4096 * 512
    assert layout.partition_type == 0x0B


def test_layout_offset_and_size_in_bytes():
    """BootPartitionLayout.offset and .size are in bytes, not sectors."""
    mbr = _make_mbr(ptype=0x0C, lba_start=2048, lba_size=102400)
    layout = find_first_fat32_partition(mbr)
    assert layout.offset == 2048 * 512       # 1 048 576 bytes
    assert layout.size == 102400 * 512       # 52 428 800 bytes
