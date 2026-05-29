"""Capture one PNG per wizard step into tour/ — for design review.

Forces fake wizard state so Steps 2-6 render with realistic content even
without SD cards / real images present. Run from project root:

    .venv\\Scripts\\python.exe scripts\\ui_tour.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

# Make the package importable when run as a loose script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.ui.app import build_app   # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "tour"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()

    # Seed realistic state so downstream steps aren't empty.
    state.setMode("both")
    state.setMasterImagePath(r"C:\images\astromechos-master-2026-05-29.img.xz")
    state.setSlaveImagePath(r"C:\images\astromechos-slave-2026-05-29.img.xz")
    state.setMasterDriveId(2)
    state.setSlaveDriveId(3)
    state.setHostnameMaster("astromech-master")
    state.setHostnameSlave("astromech-slave")
    state.setAuthorizedKeys(
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey0123456789 eric@workstation"
    )
    state.setRepoUrl("https://github.com/RickDnamps/AstromechOS")
    state.setWifiSsid("HomeNetwork")
    state.setWifiPsk("hunter2")

    # Splash auto-advances via a 1500 ms Timer inside main.qml — wait it
    # out for the step-1 capture instead of fighting it. For 2-6 we drive
    # navigation explicitly via WizardState.goto().
    plan = [
        ("00-splash",     None,   200),   # captured during the splash
        ("01-mode",       None,  1800),   # let the splash timer fire
        ("02-images",     2,      700),
        ("03-storage",    3,      700),
        ("04-customize",  4,      700),
        ("05-flash",      5,      700),
        ("06-done",       6,      700),
    ]

    idx = {"i": 0}

    def step():
        i = idx["i"]
        if i >= len(plan):
            app.quit()
            return
        name, target_step, settle_ms = plan[i]
        if target_step is not None:
            state.goto(target_step)
        QTimer.singleShot(settle_ms, lambda: capture(name))

    def capture(name: str):
        img = window.grabWindow()
        out = OUT / f"{name}.png"
        img.save(str(out))
        print(f"saved {out.relative_to(OUT.parent)}  ({img.width()}x{img.height()})")
        idx["i"] += 1
        QTimer.singleShot(80, step)

    QTimer.singleShot(150, step)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
