"""Quick probe â€” does write-at-offset-8MB succeed after DeleteVolumeMountPoint dance?

Reproduces the smallest failing step of the full E2E run: dismount the SD,
open the physical drive, write 1 MB at offset 8 MB (the old FAT32 start â€”
where the full flash hit ERROR_ACCESS_DENIED). If this probe succeeds,
the full flash should too.

NON-DESTRUCTIVE â€” only touches a single 1 MB region of the SD that already
has Pi OS bytes there. The original bytes are read first and restored after.
"""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="  %(message)s")

from astromechos_imager.platform.windows import (
    WindowsPlatformIO, enumerate_removable_drives,
)


def main() -> int:
    pio = WindowsPlatformIO()
    drives = list(enumerate_removable_drives())
    if len(drives) != 1:
        print(f"[ERR] expected 1 removable drive, got {len(drives)}")
        return 2
    target = drives[0]
    print(f"Target: phys_id={target.physical_drive_id} letters={target.drive_letters}")

    print("\n== Dismount dance ==")
    pio.lock_and_dismount(target.drive_letters)

    print("\n== Open raw device ==")
    dev = pio.open_raw_device(target.physical_drive_id)
    print(f"  size_bytes = {dev.size_bytes / 1024**3:.1f} GB")

    try:
        OFFSET = 8 * 1024 * 1024  # 8 MB â€” where the failing run died
        CHUNK = 1 << 20            # 1 MB
        print(f"\n== Probe: read 1 MB at offset {OFFSET} ==")
        original = dev.read(OFFSET, CHUNK)
        print(f"  read OK â€” {len(original)} bytes, first 4 bytes: {original[:4].hex()}")

        # Write the SAME bytes back â€” non-destructive but exercises the write path
        print(f"\n== Probe: write {CHUNK} bytes back at offset {OFFSET} ==")
        n = dev.write(OFFSET, original)
        print(f"  âœ… write OK â€” {n} bytes")

        dev.flush()
        print("  âœ… flush OK")

        # Re-read to confirm
        print(f"\n== Probe: re-read 1 MB at offset {OFFSET} ==")
        echo = dev.read(OFFSET, CHUNK)
        match = echo == original
        print(f"  re-read OK â€” bytes match: {match}")
        return 0 if match else 3
    except OSError as exc:
        print(f"\n  âŒ {type(exc).__name__}: {exc}")
        return 1
    finally:
        dev.close()
        # Re-attach the letter so Explorer shows the SD again
        if target.drive_letters:
            print(f"\n== Re-attach letter {target.drive_letters[0]} ==")
            ok = pio.attach_letter_to_unmounted_volume(target.drive_letters[0], target.physical_drive_id)
            print(f"  attach result: {ok}")


if __name__ == "__main__":
    sys.exit(main())
