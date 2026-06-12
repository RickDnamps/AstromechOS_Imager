r"""Faithful reproduction of the REAL UI flash path (no Qt).

The Qt layer (_FlashWorker.run) does nothing but call job.run() on a worker
thread — all device I/O lives in the job. So building the job through the
SAME _build_flash_job() the UI uses, with the SAME linux_account /
skip_verify wiring, and calling job.run() reproduces the exact production
flow that the fixture-only validate_native_flash.py was NOT exercising
(it skipped linux_account → no rootfs personalization, and it never went
through _build_flash_job).

Logging is wired to stdout at DEBUG so the windows.py handle-lifecycle
lines (open_raw_device -> handle, lock_and_dismount holds, CloseHandle)
are visible and we can pinpoint exactly where an Errno 5/6 fires.

Run:  $env:IMG='...pi_os_shaped.img.gz'; .\.venv\Scripts\python.exe scripts\e2e_ui_flash.py
"""
from __future__ import annotations

import io
import logging
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)

from astromechos_imager.core.diskwriter import DiskWriterProgress  # noqa: E402
from astromechos_imager.platform.windows import (  # noqa: E402
    WindowsPlatformIO,
    enumerate_removable_drives,
)
from astromechos_imager.ui.flash_view_model import _build_flash_job  # noqa: E402

IMG = Path(os.environ.get(
    "IMG", r"J:\R2-D2_Build\AstroMechOS_Imager\tests\fixtures\pi_os_shaped.img.gz"))


class FakeWizardState:
    """Mimics the QML wizardState attributes _build_flash_job reads."""
    def __init__(self, phys_id: int, img: Path):
        self.installUser = "astromech"
        self.installPassword = "astropass"
        self.hotspotPassword = "astropass"
        self.hostnameMaster = "astromech-master"
        self.hostnameSlave = "astromech-slave"
        self.repoUrl = ""
        self.wifiSsid = ""
        self.wifiPsk = ""
        self.currentRole = "master"
        self.masterImagePath = str(img)
        self.slaveImagePath = str(img)
        self.masterDriveId = phys_id
        self.slaveDriveId = phys_id
        self.verifyIntegrity = True

    def markCurrentRoleCompleted(self):
        pass


def main() -> int:
    drives = list(enumerate_removable_drives())
    if len(drives) != 1:
        print(f"[ERR] expected exactly 1 removable drive, got {len(drives)}")
        for d in drives:
            print(f"   phys_id={d.physical_drive_id} letters={d.drive_letters} "
                  f"size={d.size_bytes/1024**3:.1f}GB")
        return 2
    target = drives[0]
    print(f"\n=== TARGET phys_id={target.physical_drive_id} "
          f"letters={target.drive_letters} size={target.size_bytes/1024**3:.1f}GB ===\n")

    pio = WindowsPlatformIO()
    ws = FakeWizardState(target.physical_drive_id, IMG)

    # EXACT UI job builder — sets linux_account + skip_verify like production.
    job = _build_flash_job(ws, platform_io=pio)
    if job is None:
        print("[ERR] _build_flash_job returned None")
        return 2
    print(f"job: role={job.role} skip_verify={job.skip_verify} "
          f"linux_account={'SET' if job.linux_account else 'None'}\n")

    last = {"t": 0.0}
    def on_progress(p: DiskWriterProgress) -> None:
        now = time.monotonic()
        if now - last["t"] > 1.0 or p.phase in ("verify", "customizing", "preparing"):
            last["t"] = now
            pct = (p.bytes_done / p.bytes_total * 100) if p.bytes_total else 0
            print(f"  [{p.phase}] {p.bytes_done/1024**2:.0f}MB ({pct:.0f}%) "
                  f"@ {p.throughput_bps/1024**2:.1f}MB/s")
    job.on_progress = on_progress

    print("=== job.run() ===")
    t0 = time.monotonic()
    result = job.run()
    dt = time.monotonic() - t0
    print(f"\n=== job.run() -> ok={result.ok} in {dt:.0f}s ===")
    if not result.ok:
        print(f"  ERROR: {result.error!r}")
        import traceback
        cause = getattr(result.error, "__cause__", None)
        if cause is not None:
            print("  --- __cause__ traceback ---")
            traceback.print_exception(type(cause), cause, cause.__traceback__)
        return 1
    print(f"  ok, sha256={result.source_sha256[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
