"""Capture one PNG per wizard step into screenshots/ — for design review.

Forces fake wizard state so Steps 2-6 render with realistic content even
without SD cards / real images present. 6-step wizard:
  Mode → Images → Storage → Customize → Flash → Done.
Captures both Dark and Light themes back-to-back (sun/moon toggle wiring).
Run from project root:

    .venv\\Scripts\\python.exe scripts\\ui_tour.py

Output directory is gitignored (see .gitignore -> screenshots/).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer

# Make the package importable when run as a loose script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.ui.app import build_app   # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()

    # Seed realistic wizard state — 6-step wizard with restored Customize.
    state.setMode("both")
    state.setMasterImagePath(r"C:\images\AstromechOS-master-2026-05-30.img.xz")
    state.setSlaveImagePath(r"C:\images\AstromechOS-slave-2026-05-30.img.xz")
    state.setMasterDriveId(2)
    state.setSlaveDriveId(3)
    state.setHostnameMaster("astromech-master")
    state.setHostnameSlave("astromech-slave")
    state.setRepoUrl("https://github.com/RickDnamps/AstromechOS")
    # Step 4 Customize — keep the pre-filled defaults from WizardState
    # (astromech / astropass / astropass) so the screenshot shows what
    # a fresh operator sees on first launch. Only the optional Wi-Fi
    # pair is seeded so the screenshot demonstrates a "fully configured"
    # state with green ✓ glyphs everywhere.
    state.setWifiSsid("HomeNetwork")
    state.setWifiPsk("hunter2024")

    # Splash auto-advances via a 1500 ms Timer inside main.qml — wait it
    # out for the step-1 capture instead of fighting it. For 2-6 we drive
    # navigation explicitly via WizardState.goto(). We capture each step
    # in dark mode, then re-walk in light mode.
    base_plan = [
        ("00-splash",      None,   200),   # captured during the splash
        ("01-mode",        None,  1800),   # let the splash timer fire
        ("02-images",         2,   700),
        ("03-storage",        3,   700),
        ("04-customize",      4,   700),
        ("05-flash",          5,   700),
        ("06-done",           6,   700),
    ]
    themes = ["dark", "light"]

    # Resolve the ThemeManager — exposed as a Python QObject via the
    # context, but also kept alive by build_app() on engine.themeManager.
    theme_mgr = getattr(engine, "themeManager", None)

    plan = []
    for theme_name in themes:
        for name, step, settle in base_plan:
            plan.append((f"{theme_name}/{name}", theme_name, step, settle))

    idx = {"i": 0}

    def step():
        i = idx["i"]
        if i >= len(plan):
            app.quit()
            return
        name, theme_name, target_step, settle_ms = plan[i]
        if theme_mgr is not None:
            theme_mgr.setMode(theme_name)
        # Reset wizard back to step 1 between themes so the splash logic
        # is consistent.
        if name.endswith("00-splash") and i > 0:
            state.goto(1)   # ensure fresh navigation surface
        if target_step is not None:
            state.goto(target_step)
        QTimer.singleShot(settle_ms, lambda: capture(name))

    def capture(name: str):
        out = OUT / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img = window.grabWindow()
        img.save(str(out))
        print(f"saved {out.relative_to(OUT.parent)}  ({img.width()}x{img.height()})")
        idx["i"] += 1
        QTimer.singleShot(80, step)

    QTimer.singleShot(150, step)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
