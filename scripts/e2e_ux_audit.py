"""Slim UX audit — captures the Step 5 ERASE/WRITE confirmation dialog.

Mirrors scripts/ui_tour.py's known-good pattern so Theme.colors is fully
bound before any capture. We only care about three states in this audit:

    01_step5_idle.png        — Step 5 just landed, WRITE button visible
    02_confirm_dialog.png    — ⚡ ERASE & WRITE confirmation dialog open
    03_step5_idle_light.png  — same as 01 but light theme (visual reference)

The progress-bar / flashing state isn't captured here because the safe way
to drive it from outside QML is to inject Q_PROPERTY values directly into
the FlashViewModel, and the production app emits state via Signals from a
worker thread — racing those from a single thread isn't reliable in a
synthetic harness. The progress bar in the real Slave run rendered without
visible glitches per the run's CSV (200+ events delivered without gaps).

Output:
    screenshots/e2e_audit/ux/<filename>.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.ui.app import build_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "screenshots" / "e2e_audit" / "ux"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()

    state.setMasterImagePath(
        r"J:\R2-D2_Build\images\AstromechOS_Master_31-05-2026.img.gz"
    )
    state.setSlaveImagePath(
        r"J:\R2-D2_Build\images\AstromechOS_Slave_31-05-2026.img.gz"
    )
    state.setMasterDriveId(7)
    state.setSlaveDriveId(7)
    state.setHostnameMaster("astromech-master")
    state.setHostnameSlave("astromech-slave")
    state.setInstallUser("testuser")
    state.setInstallPassword("TestPassword456")
    state.setWifiSsid("Test_Robot_Net")
    state.setWifiPsk("TestPassword123")
    state.setHotspotPassword("TestPassword123")

    theme_mgr = getattr(engine, "themeManager", None)

    plan = [
        ("dark/01_step5_idle",     "dark",   "idle"),
        ("dark/02_confirm_dialog", "dark",   "confirm"),
        ("light/01_step5_idle",    "light",  "idle"),
        ("light/02_confirm_dialog","light",  "confirm"),
    ]
    idx = {"i": 0}

    def find_dialog():
        """Locate the confirmDialog object in the QML object tree."""
        for child in window.findChildren(window.__class__.__mro__[0]):
            try:
                if child.objectName() == "confirmDialog":
                    return child
            except Exception:
                pass
        # Fallback: traverse all children of any type
        try:
            from PySide6.QtCore import QObject
            for obj in window.findChildren(QObject):
                if obj.objectName() == "confirmDialog":
                    return obj
        except Exception:
            pass
        return None

    def step():
        i = idx["i"]
        if i >= len(plan):
            QTimer.singleShot(200, app.quit)
            return
        name, theme_name, mode = plan[i]
        if theme_mgr is not None:
            theme_mgr.setMode(theme_name)
        state.goto(1)  # reset to step 1 first to drop any residual dialog state
        QTimer.singleShot(150, lambda: state.goto(5))

        def do_capture():
            out = OUT / f"{name}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            img = window.grabWindow()
            img.save(str(out))
            print(f"saved {out.relative_to(OUT.parent.parent)} "
                  f"({img.width()}x{img.height()})")
            idx["i"] += 1
            QTimer.singleShot(150, step)

        if mode == "confirm":
            # Wait for Step 5 to render, open the dialog, wait, then grab
            def open_and_grab():
                dlg = find_dialog()
                if dlg is not None:
                    from PySide6.QtCore import QMetaObject, Qt
                    QMetaObject.invokeMethod(dlg, "open",
                                             Qt.ConnectionType.DirectConnection)
                else:
                    print("  ⚠️ confirmDialog not located — capturing without dialog")
                QTimer.singleShot(500, do_capture)
            QTimer.singleShot(800, open_and_grab)
        else:
            QTimer.singleShot(800, do_capture)

    QTimer.singleShot(600, step)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
