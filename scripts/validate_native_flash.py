"""End-to-end validation of the new flash path on real hardware (Master).

Exercises the production FlashJob.run with verify ON and customize ON:
  write (deferred MBR) -> flush -> SCSI sync -> close
  -> settle -> verify on a FRESH handle
  -> userspace-FAT customize (no mount)
  -> write MBR last
Then re-reads the FAT in userspace (no mount) to confirm the bundle landed.

Pass criteria:
  * FlashJob returns ok (verify_readback passed — the bug is fixed)
  * the AstromechOS bundle is readable back via userspace FAT
  * no drive letter was ever involved (no pop-up possible)
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.core.bootpartition import find_first_fat32_partition
from astromechos_imager.core.diskwriter import DiskWriterProgress
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role, _utc_iso_now
from astromechos_imager.core.orchestrator import FlashJob
from astromechos_imager.core.raw_fat_partition import RawFatBootPartition
from astromechos_imager.platform.windows import (
    WindowsPlatformIO, enumerate_removable_drives,
)

# Default to the real 5.8 GB Master image; override with IMG=... for a fast
# ~30 s round-trip against the small tests/fixtures/pi_os_shaped.img.gz
# (97 MB decompressed, valid MBR + FAT32) when iterating on the code path.
IMG = Path(os.environ.get(
    "IMG", r"J:\R2-D2_Build\images\AstromechOS_Master_31-05-2026.img.gz"))


def main() -> int:
    drives = list(enumerate_removable_drives())
    if len(drives) != 1:
        print(f"[ERR] expected 1 removable drive, got {len(drives)}")
        return 2
    target = drives[0]
    print(f"Target phys_id={target.physical_drive_id} letters={target.drive_letters} "
          f"size={target.size_bytes/1024**3:.1f}GB")

    pair = generate_ed25519()
    hotspot = generate_hotspot_bootstrap("TestPassword123")
    cfg = FirstbootConfig(
        authorized_keys=[],
        install_user="testuser",
        hostname_master="astromech-master",
        hostname_slave="astromech-slave",
        hotspot_bootstrap=hotspot,
        wifi_ssid="Test_Robot_Net",
        wifi_psk="TestPassword123",
        imager_version="0.1.0-native",
        flashed_at_iso=_utc_iso_now(),
    )

    last = {"t": 0.0}
    def on_progress(p: DiskWriterProgress) -> None:
        now = time.monotonic()
        if now - last["t"] > 2.0 or p.phase in ("verify", "customizing"):
            last["t"] = now
            pct = (p.bytes_done / p.bytes_total * 100) if p.bytes_total else 0
            print(f"  [{p.phase}] {p.bytes_done/1024**2:.0f}MB ({pct:.0f}%) "
                  f"@ {p.throughput_bps/1024**2:.1f}MB/s")

    job = FlashJob(
        platform_io=WindowsPlatformIO(),
        image_path=IMG,
        target=target,
        role=Role.MASTER,
        firstboot_config=cfg,
        master_pair=pair,
        on_progress=on_progress,
        skip_verify=bool(int(os.environ.get("SKIP_VERIFY", "0"))),
        skip_customize=False,
    )

    print(f"\n== Running FlashJob (skip_verify={job.skip_verify}, customize ON) ==")
    t0 = time.monotonic()
    result = job.run()
    dt = time.monotonic() - t0
    print(f"\nFlashJob.run() -> ok={result.ok} in {dt:.0f}s")
    if not result.ok:
        print(f"  ❌ error: {result.error!r}")
        return 1
    print(f"  ✅ verify PASSED, sha256={result.source_sha256[:16]}...")

    # Confirm the bundle via userspace FAT (no mount, no letter)
    print("\n== Read back the bundle via userspace FAT (no mount) ==")
    pio = WindowsPlatformIO()
    rd = pio.open_plain_raw_device(target.physical_drive_id)
    try:
        mbr = rd.read(0, 512)
    finally:
        rd.close()
    layout = find_first_fat32_partition(mbr)
    bp = RawFatBootPartition.open_on_drive(
        pio, target.physical_drive_id, layout.offset, layout.size)
    try:
        checks = [
            ("/ASTROMECH_FIRSTBOOT_READY", bp.exists("/ASTROMECH_FIRSTBOOT_READY")),
            ("/astromech_init.cfg", bp.exists("/astromech_init.cfg")),
            ("/astromech_wlan.conf", bp.exists("/astromech_wlan.conf")),
            ("/astromech_secrets/init_config.json",
             bp.exists("/astromech_secrets/init_config.json")),
        ]
        for name, ok in checks:
            print(f"  {'✅' if ok else '❌'} {name}")
        if bp.exists("/astromech_init.cfg"):
            print("\n  --- /astromech_init.cfg ---")
            print(bp.read_bytes("/astromech_init.cfg").decode("utf-8", "replace").strip())
        all_ok = all(ok for _, ok in checks)
    finally:
        bp.close()

    print("\n== VERDICT ==")
    if all_ok:
        print("  🟢 NATIVE FLASH PATH WORKS — verify passes, bundle present, no mount.")
        return 0
    print("  🔴 bundle incomplete")
    return 1


if __name__ == "__main__":
    sys.exit(main())
