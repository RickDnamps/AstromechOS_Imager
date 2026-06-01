"""Drive the REAL Qt FlashViewModel end-to-end (the actual app interface).

Unlike e2e_ui_flash.py (which calls job.run() directly), this instantiates
the real FlashViewModel and calls startWithJob(), so the flash runs on the
real _FlashWorker QThread exactly as the GUI does it — same threading, same
signal plumbing. Logs go to stdout at DEBUG so every PHASE / handle / Errno
line is visible.

Run:  $env:IMG='...'; .\.venv\Scripts\python.exe scripts\e2e_qt_flash.py
"""
from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S", stream=sys.stdout,
)

from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from astromechos_imager.platform.windows import (  # noqa: E402
    WindowsPlatformIO, enumerate_removable_drives,
)
from astromechos_imager.ui.flash_view_model import FlashViewModel, _build_flash_job  # noqa: E402

IMG = Path(os.environ.get(
    "IMG", r"J:\R2-D2_Build\AstroMechOS_Imager\tests\fixtures\pi_os_shaped.img.gz"))


class FakeWizardState(QObject):
    sessionSsidChanged = Signal(str)

    def __init__(self, phys_id: int, img: Path):
        super().__init__()
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
        print(">>> wizard_state.markCurrentRoleCompleted() called")


def main() -> int:
    app = QApplication(sys.argv)
    drives = list(enumerate_removable_drives())
    if len(drives) != 1:
        print(f"[ERR] expected exactly 1 removable drive, got {len(drives)}")
        return 2
    target = drives[0]
    print(f"\n=== TARGET phys_id={target.physical_drive_id} "
          f"letters={target.drive_letters} ===\n")

    ws = FakeWizardState(target.physical_drive_id, IMG)
    vm = FlashViewModel(ws)
    job = _build_flash_job(ws, platform_io=WindowsPlatformIO())
    if job is None:
        print("[ERR] _build_flash_job returned None")
        return 2

    def on_status():
        st = vm.status
        print(f">>> STATUS = {st}")
        if st in ("done", "error", "cancelled"):
            if st == "error":
                print(f"\n!!! ERROR MESSAGE: {vm.errorMessage!r}")
            QTimer.singleShot(200, app.quit)

    def on_phase():
        print(f"    master phase={vm.masterPhase!r} progress={vm.masterProgress:.2f}")

    vm.statusChanged.connect(on_status)
    vm.masterPhaseChanged.connect(on_phase)

    # Safety timeout so the script never hangs forever.
    QTimer.singleShot(600_000, app.quit)

    print("=== vm.startWithJob(job) — REAL Qt worker thread ===")
    vm.startWithJob(job)
    app.exec()

    print(f"\n=== FINAL status={vm.status} ===")
    if vm.status == "error":
        print(f"  errorMessage: {vm.errorMessage}")
        return 1
    return 0 if vm.status == "done" else 3


if __name__ == "__main__":
    sys.exit(main())
