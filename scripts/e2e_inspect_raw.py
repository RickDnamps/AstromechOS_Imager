"""Inspect the FAT32 boot partition via direct raw-device read (bypassing Windows).

Goal: confirm whether the FirstbootBundle was actually written to the SD by the
orchestrator's customize step. The Windows-mounted I:\\ view may be stale due
to auto-mount caching during the raw block write — pyfatfs reading directly
from \\.\PHYSICALDRIVE7 will show the on-disk truth.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.core.bootpartition import (
    PyFatFsBootPartition, find_first_fat32_partition,
)
from astromechos_imager.platform.windows import enumerate_removable_drives


def main() -> int:
    drives = list(enumerate_removable_drives())
    if not drives or drives[0].physical_drive_id != 7:
        print("[ERR] expected single removable drive @ PhysicalDrive7")
        return 2
    dev_path = drives[0].device_path  # "\\\\.\\PHYSICALDRIVE7"
    print(f"Device: {dev_path}")

    # Read MBR via raw stdlib (pyfatfs can't open a raw block device — needs a layout)
    # Actually pyfatfs CAN read from \\\\.\\PHYSICALDRIVE7 if Python's open()
    # cooperates. Let's try it.
    print("Reading MBR…")
    with open(dev_path, "rb", buffering=0) as f:
        mbr = f.read(512)
    print(f"MBR signature: {mbr[510:512].hex()} (expect 55aa)")

    layout = find_first_fat32_partition(mbr)
    print(f"FAT32 partition: offset={layout.offset / 1024**2:.1f} MB, "
          f"size={layout.size / 1024**2:.1f} MB, type=0x{layout.partition_type:02X}")

    print(f"\nOpening pyfatfs on raw device at offset {layout.offset}…")
    try:
        bp = PyFatFsBootPartition(dev_path, layout)
    except Exception as e:
        print(f"[ERR] pyfatfs open failed: {e!r}")
        return 3
    print("pyfatfs opened OK.")

    targets = [
        "/ASTROMECH_FIRSTBOOT_READY",
        "/astromech_init.cfg",
        "/astromech_wlan.conf",
        "/astromech_secrets",
        "/astromech_secrets/init_config.json",
        "/astromech_secrets/authorized_keys",
        "/astromech_secrets/id_ed25519",
        "/astromech_secrets/id_ed25519.pub",
        "/cmdline.txt",
    ]
    print("\n== Probe customization paths ==")
    for t in targets:
        try:
            exists = bp.exists(t)
        except Exception as e:
            exists = f"err {e!r}"
        print(f"  {'✅' if exists is True else '❌' if exists is False else '?'} {t}: {exists}")

    print("\n== Read selected file contents ==")
    for t in ("/astromech_init.cfg", "/astromech_wlan.conf",
              "/astromech_secrets/init_config.json", "/cmdline.txt"):
        if bp.exists(t):
            try:
                data = bp.read_bytes(t)
                print(f"\n--- {t} ({len(data)} B) ---")
                print(data.decode("utf-8", errors="replace").strip())
            except Exception as e:
                print(f"  [ERR] read {t}: {e!r}")

    bp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
