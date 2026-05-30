"""Programmatic validation of Step 4 SecurityNote popups.

Captures Step 4 with each Security note popup OPEN in turn, so the
operator can visually verify popup positioning (right edge inside
the card, vertical placement below the icon, text readable) without
manually clicking anything.

Run:
    .venv\\Scripts\\python.exe scripts\\validate_security_notes.py
Output: screenshots/validation/step4_<theme>_<scenario>.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.ui.app import build_app   # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "screenshots" / "validation"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()
    state.setMode("both")
    theme_mgr = getattr(engine, "themeManager", None)

    plan = []
    for theme_name in ("light", "dark"):
        plan += [
            (theme_name, "closed", None, 800),
            (theme_name, "login_open",   "LINUXACCOUNTSecNote",         800),
            (theme_name, "login_closed", None,                          400),
            (theme_name, "hotspot_open", "PRIVATEROBOTHOTSPOTSecNote",  800),
            (theme_name, "hotspot_closed", None,                        400),
        ]

    idx = {"i": 0}

    def jump():
        state.goto(4)
        QTimer.singleShot(600, step)

    def step():
        i = idx["i"]
        if i >= len(plan):
            print(f"\n✅ Captured {len([1 for _ in plan if _[2] is None or _[1].endswith('open')])} screenshots in {OUT.relative_to(OUT.parent.parent)}/")
            app.quit()
            return
        theme_name, scenario, sec_note_id, settle_ms = plan[i]
        if theme_mgr is not None:
            theme_mgr.setMode(theme_name)
        # Close any open popup first
        for n in ("LINUXACCOUNTSecNote", "PRIVATEROBOTHOTSPOTSecNote"):
            sn = window.findChild(QObject, n)
            if sn is not None:
                sn.closePopup()
        # Open requested popup
        if sec_note_id:
            sn = window.findChild(QObject, sec_note_id)
            if sn is None:
                print(f"  ⚠️ findChild({sec_note_id!r}) returned None — popup not opened")
            else:
                sn.openPopup()
        QTimer.singleShot(settle_ms, capture)

    def capture():
        i = idx["i"]
        theme_name, scenario, _, _ = plan[i]
        if scenario.endswith("closed") and not scenario.startswith(("login", "hotspot")):
            name = f"step4_{theme_name}_{scenario}"
        elif scenario.startswith(("login_open", "hotspot_open")):
            name = f"step4_{theme_name}_{scenario}"
        else:
            # Don't save the in-between "closed" cleanup steps
            idx["i"] += 1
            QTimer.singleShot(80, step)
            return
        out = OUT / f"{name}.png"
        img = window.grabWindow()
        img.save(str(out))
        size = out.stat().st_size
        print(f"  saved {out.relative_to(OUT.parent.parent)}  ({img.width()}x{img.height()}, {size//1024} KB)")
        idx["i"] += 1
        QTimer.singleShot(80, step)

    QTimer.singleShot(1700, jump)   # let the splash settle
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
