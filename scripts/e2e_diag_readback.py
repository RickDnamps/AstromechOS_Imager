"""Forensic diagnostic — what's actually on the disk after a failed run?

Inspects the raw bytes on PhysicalDrive7 at the regions we'd expect to
differ if Windows wrote System Volume Information after auto-mounting
via FAT32 signature scan:
  - offset 0..512        (MBR — should be deferred-first-block content)
  - offset 8 MB..8 MB+4K (FAT32 boot sector — source bytes vs disk bytes)
  - search for "$Volume" / "INFO" strings inside the FAT32 partition
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.platform.windows import (
    WindowsPlatformIO, enumerate_removable_drives,
)


def main() -> int:
    pio = WindowsPlatformIO()
    drives = list(enumerate_removable_drives())
    if not drives:
        print("[ERR] no removable drives")
        return 2
    target = drives[0]
    print(f"Target: phys_id={target.physical_drive_id} letters={target.drive_letters}")

    print("\n== Dismount + open ==")
    pio.lock_and_dismount(target.drive_letters)
    dev = pio.open_raw_device(target.physical_drive_id)

    try:
        print("\n== Read MBR (offset 0, 512 B) ==")
        mbr = dev.read(0, 512)
        is_zero = all(b == 0 for b in mbr)
        sig = mbr[510:512].hex()
        print(f"  zero? {is_zero}  signature: {sig}  first 16: {mbr[:16].hex()}")

        print("\n== Read FAT32 boot sector (offset 8 MB, 512 B) ==")
        fat = dev.read(8 * 1024 * 1024, 512)
        is_zero = all(b == 0 for b in fat)
        first16 = fat[:16].hex()
        oem = fat[3:11]
        sig = fat[510:512].hex()
        print(f"  zero? {is_zero}  signature: {sig}  OEM: {oem!r}  first 16: {first16}")

        # Read the first 16 MB of the FAT32 partition (= offset 8M..24M of disk),
        # look for "System Volume Information" signature strings written by Windows.
        print("\n== Scan first 16 MB of FAT32 partition for SVI markers ==")
        chunk = dev.read(8 * 1024 * 1024, 16 * 1024 * 1024)
        markers = [
            (b"SYSTEM~1", "8.3 short name for System Volume Information"),
            (b"System Volume Information", "long name UTF-16 LE would have nulls between chars"),
            (b"S\x00y\x00s\x00t\x00e\x00m\x00", "System (UTF-16 LE) inside an LFN entry"),
            (b"$Volume", "NTFS-ish artifact"),
            (b"IndexerVolumeGuid", "Windows Search marker"),
            (b"WPSettings.dat", "Windows portable settings"),
        ]
        any_found = False
        for needle, label in markers:
            count = chunk.count(needle)
            if count:
                any_found = True
                pos = chunk.find(needle)
                ctx = chunk[max(0, pos - 8):pos + len(needle) + 8]
                print(f"  ⚠️ FOUND {needle!r}  ({label})  x{count}  at +{pos} bytes")
                print(f"     context: {ctx!r}")
        if not any_found:
            print("  no SVI markers detected in first 16 MB")

        return 0
    finally:
        dev.close()
        if target.drive_letters:
            pio.attach_letter_to_unmounted_volume(target.drive_letters[0])


if __name__ == "__main__":
    sys.exit(main())
