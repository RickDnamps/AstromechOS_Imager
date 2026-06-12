"""Capture the ⚡ WRITE confirmation dialog in both themes for UX review.

Seeds enough wizard state to land on Step 5 (Flash), then programmatically
opens ``confirmDialog`` (the modal that warns "ERASE TARGET DRIVE(S)?")
via findChild + .open(). Captures both light + dark.

Output: screenshots/validation/write_dialog_<theme>.png

Run:
    .venv\\Scripts\\python.exe scripts\\capture_write_dialog.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

from astromechos_imager.ui.app import build_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "screenshots" / "validation"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()

    # Seed minimal state — sequential workflow: master role this cycle.
    state.setMasterImagePath(r"C:\images\AstromechOS-master-2026-05-30.img.xz")
    state.setMasterDriveId(2)
    state.setCurrentRole("master")
    theme_mgr = getattr(engine, "themeManager", None)

    plan = ["light", "dark"]
    idx = {"i": 0}

    def jump():
        state.goto(5)
        QTimer.singleShot(500, do_capture)

    def do_capture():
        i = idx["i"]
        if i >= len(plan):
            app.quit()
            return
        theme_name = plan[i]
        if theme_mgr is not None:
            theme_mgr.setMode(theme_name)
        # Find the Dialog by traversing children. Qt assigns the QML id
        # but not the objectName — we walk all children and pick the
        # first whose metaObject className contains "Dialog".
        dlg = None
        for child in window.findChildren(QObject):
            cls = child.metaObject().className() if child.metaObject() else ""
            if "Dialog" in cls and hasattr(child, "open"):
                # Skip the splash / non-modal popups; keep the modal one.
                try:
                    is_modal = child.property("modal")
                    if is_modal:
                        dlg = child
                        break
                except Exception:
                    pass
        if dlg is None:
            print(f"  ⚠️ no modal Dialog found for {theme_name}")
        else:
            dlg.open()
        QTimer.singleShot(700, lambda: capture(theme_name, dlg))

    def capture(theme_name, dlg):
        out = OUT / f"write_dialog_{theme_name}.png"
        img = window.grabWindow()
        img.save(str(out))
        print(f"  saved {out.relative_to(OUT.parent.parent)}  ({img.width()}x{img.height()}, {out.stat().st_size//1024} KB)")
        if dlg is not None:
            with contextlib.suppress(Exception):
                dlg.close()
        idx["i"] += 1
        QTimer.singleShot(120, do_capture)

    QTimer.singleShot(1700, jump)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
