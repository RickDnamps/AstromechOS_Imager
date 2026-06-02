"""Capture one PNG per README walkthrough step into screenshots/.

Forces fake wizard state so the screens render with realistic content even
without SD cards / real images present. The live wizard is 7 steps —
1 Landing · 2 Config(Customize) · 3 Images · 4 Role · 5 Ops · 6 Cycle ·
7 Complete — but the README tells the story in a different order, so each
capture label below is paired with the wizard step (``goto`` index) whose
SCREEN it must show. Keep the two in sync if either changes.
Captures both Dark and Light themes back-to-back (sun/moon toggle wiring).
Run from project root:

    .venv\\Scripts\\python.exe scripts\\ui_tour.py

Output directory is gitignored (see .gitignore -> screenshots/).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QObject, QMetaObject

# Make the package importable when run as a loose script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.ui.app import build_app   # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()

    # Seed realistic wizard state — 7-step sequential wizard. The legacy
    # mode picker is gone; Phase B will update the QML capture plan.
    state.setMasterImagePath(r"C:\images\AstromechOS-master-2026-05-30.img.xz")
    state.setSlaveImagePath(r"C:\images\AstromechOS-slave-2026-05-30.img.xz")
    state.setMasterDriveId(2)
    state.setSlaveDriveId(3)
    state.setHostnameMaster("astromech-master")
    state.setHostnameSlave("astromech-slave")
    state.setRepoUrl("https://github.com/RickDnamps/AstromechOS")
    # Step 4 Customize — leave Robot Login + Hotspot blank so the
    # screenshot shows the empty-with-placeholder state a fresh operator
    # sees on first launch (placeholders read "astromech" / "astropass"
    # / "astropass" — the backend substitutes them at flash time via
    # the non-blocking fallback). Seed only the optional Wi-Fi pair so
    # the third card demonstrates a "filled" state too.
    state.setWifiSsid("HomeNetwork")
    state.setWifiPsk("hunter2024")

    # Splash auto-advances via a 1500 ms Timer inside main.qml — wait it
    # out for the step-1 capture instead of fighting it. For 2-6 we drive
    # navigation explicitly via WizardState.goto(). We capture each step
    # in dark mode, then re-walk in light mode.
    # 4th element = optional action to run after navigating, before capture.
    # (capture-label, goto-step, settle-ms, action). The label tracks the
    # README narrative; goto-step is the LIVE wizard step whose screen it shows.
    base_plan = [
        ("00-splash",                None, 2200, None),  # mid-loader (bar ~60%)
        ("01-landing",               None, 1800, None),  # splash timer → step 1 Landing
        ("02-target-drives",            4,  700, None),  # step 4 — Role / INSERT SD CARD
        ("03-security-validation",      3,  700, None),  # step 3 — Images (role marker)
        ("04-customize",                2,  700, None),  # step 2 — Config (account/hotspot/wifi)
        ("05-confirm-flash",            5,  700, None),  # step 5 — Ops (verify + flash)
        ("05b-write-confirm",           5,  700, "open_confirm"),  # ⚡ WRITE dialog
        ("06-complete",                 7,  700, None),  # step 7 — Complete
    ]
    themes = ["dark", "light"]

    # Resolve the ThemeManager — exposed as a Python QObject via the
    # context, but also kept alive by build_app() on engine.themeManager.
    theme_mgr = getattr(engine, "themeManager", None)

    plan = []
    for theme_name in themes:
        for name, step, settle, action in base_plan:
            plan.append((f"{theme_name}/{name}", theme_name, step, settle, action))

    idx = {"i": 0}

    def _confirm_dialog():
        return window.findChild(QObject, "confirmDialog")

    def step():
        i = idx["i"]
        if i >= len(plan):
            app.quit()
            return
        name, theme_name, target_step, settle_ms, action = plan[i]
        if theme_mgr is not None:
            theme_mgr.setMode(theme_name)
        # Close any lingering modal confirm dialog from a previous capture
        # before navigating (it belongs to the Step 5 page being left).
        dlg = _confirm_dialog()
        if dlg is not None:
            QMetaObject.invokeMethod(dlg, "close")
        # Reset wizard back to step 1 between themes so the splash logic
        # is consistent.
        if name.endswith("00-splash") and i > 0:
            state.goto(1)   # ensure fresh navigation surface
        if target_step is not None:
            state.goto(target_step)
        # Optional action: pop the ⚡ WRITE confirmation dialog open so we can
        # capture the "ERASE TARGET DRIVE(S)?" warning the operator sees.
        if action == "open_confirm":
            def _open():
                d = _confirm_dialog()
                if d is not None:
                    QMetaObject.invokeMethod(d, "open")
            QTimer.singleShot(200, _open)
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
