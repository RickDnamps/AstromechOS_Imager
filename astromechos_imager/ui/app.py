"""QApplication entry point + crash hook for AstromechOS Imager."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from astromechos_imager.ui.messages import M
from astromechos_imager.ui.wizard_state import WizardState
from astromechos_imager.ui.flash_view_model import FlashViewModel


def _excepthook(exc_type, exc_value, tb) -> None:
    """Last-resort crash logger. Replaced by the JSONL logging hook in a later phase."""
    sys.stderr.write("\n=== AstromechOS Imager — UNCAUGHT EXCEPTION ===\n")
    traceback.print_exception(exc_type, exc_value, tb)


def splash_asset_path() -> Path:
    """Resolve the startup splash PNG in dev and frozen (PyInstaller) modes."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "astromechos_imager" / "ui" / "resources" / "images" / "startup_screen_final.png"
    return Path(__file__).resolve().parent / "resources" / "images" / "startup_screen_final.png"


def build_app() -> tuple[QGuiApplication, QQmlApplicationEngine, WizardState]:
    """Construct the QApplication + QML engine + WizardState. Used by main() and tests."""
    # Reuse existing instance if pytest-qt already created one
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.setApplicationName(M["app_title"])
    sys.excepthook = _excepthook

    state = WizardState()
    flash_vm = FlashViewModel(state)
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("splashImageUrl", QUrl.fromLocalFile(str(splash_asset_path())))
    ctx.setContextProperty("wizardState", state)
    ctx.setContextProperty("flashViewModel", flash_vm)
    engine.flashViewModel = flash_vm   # keepalive

    # Drive list model — Windows-only; tests inject their own
    if sys.platform == "win32":
        try:
            from astromechos_imager.platform.windows import WindowsPlatformIO
            from astromechos_imager.ui.drive_list_model import DriveListModel
            drive_model = DriveListModel(WindowsPlatformIO())
            drive_model.start_polling()
            ctx.setContextProperty("driveListModel", drive_model)
            # Hold a reference so it doesn't get GC'd
            engine.driveListModel = drive_model
        except Exception:
            # WMI may fail in CI offscreen environments — just don't expose the model
            pass

    qml_main = Path(__file__).resolve().parent / "qml" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_main)))
    return app, engine, state


def main() -> int:
    app, _engine, _state = build_app()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
