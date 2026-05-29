"""QApplication entry point + crash hook for AstromechOS Imager."""
from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from pathlib import Path


def _startup_log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    d = Path(base) / "AstromechOS_Imager"
    d.mkdir(parents=True, exist_ok=True)
    return d / "startup.log"


# Redirect stdout/stderr to a file BEFORE importing PySide6 — when the app is
# frozen with console=False, sys.stderr is a no-op object, so Qt warnings,
# QML errors and Python tracebacks all disappear into the void. The file
# capture below is the only thing that makes the GUI build diagnosable.
_LOG_FH = None
if getattr(sys, "frozen", False):
    try:
        _LOG_FH = open(_startup_log_path(), "w", encoding="utf-8", buffering=1)
        sys.stdout = _LOG_FH
        sys.stderr = _LOG_FH
        faulthandler.enable(file=_LOG_FH)
    except OSError:
        pass  # last resort — better to launch without logging than to crash

from PySide6.QtCore import QUrl, qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from astromechos_imager.ui.messages import M
from astromechos_imager.ui.wizard_state import WizardState
from astromechos_imager.ui.flash_view_model import FlashViewModel
from astromechos_imager.ui.theme_manager import ThemeManager


_QT_MSG_LEVEL = {
    QtMsgType.QtDebugMsg: "DEBUG",
    QtMsgType.QtInfoMsg: "INFO",
    QtMsgType.QtWarningMsg: "WARN",
    QtMsgType.QtCriticalMsg: "CRIT",
    QtMsgType.QtFatalMsg: "FATAL",
}


def _qt_message_handler(msg_type, ctx, message) -> None:
    sink = sys.stderr if sys.stderr is not None else sys.__stderr__
    if sink is None:
        return
    level = _QT_MSG_LEVEL.get(msg_type, "?")
    where = f" ({ctx.file}:{ctx.line})" if ctx and ctx.file else ""
    sink.write(f"[Qt {level}]{where} {message}\n")


def _excepthook(exc_type, exc_value, tb) -> None:
    """Last-resort crash logger. Replaced by the JSONL logging hook in a later phase."""
    sink = sys.stderr if sys.stderr is not None else sys.__stderr__
    if sink is None:
        return
    sink.write("\n=== AstromechOS Imager — UNCAUGHT EXCEPTION ===\n")
    traceback.print_exception(exc_type, exc_value, tb, file=sink)


def _resources_root() -> Path:
    """Return the resources/ root in dev or frozen mode."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "astromechos_imager" / "ui" / "resources"
    return Path(__file__).resolve().parent / "resources"


def splash_asset_path() -> Path:
    return _resources_root() / "images" / "startup_screen_final.png"


def _window_icon_path() -> Path | None:
    """Resolve images/AstromechOS_Imager.ico in dev and frozen modes.
    Returned path may not exist (e.g. icon not yet generated) — callers
    must check is_file()."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "images" / "AstromechOS_Imager.ico"
    return Path(__file__).resolve().parents[2] / "images" / "AstromechOS_Imager.ico"


def _load_fonts() -> None:
    """Register every .otf in resources/fonts with QFontDatabase so QML can
    reference them by family (e.g. font.family: \"Orbitron\"). The bundle
    ships Orbitron as OpenType (cleaner geometric rendering than TTF for
    this typeface). Silently skips errors — Qt falls back to Segoe UI
    automatically when the family is unavailable."""
    fonts_dir = _resources_root() / "fonts"
    if not fonts_dir.is_dir():
        return
    for font_path in fonts_dir.glob("*.otf"):
        QFontDatabase.addApplicationFont(str(font_path))


def _qml_main_path() -> Path:
    """Resolve main.qml in dev and frozen modes.

    In dev: __file__ = astromechos_imager/ui/app.py → .parent/qml/main.qml.
    In frozen: app.py is the entry script, so __file__ = <bundle>/_internal/app.py
    (NOT inside the package layout). We have to use sys._MEIPASS instead.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "astromechos_imager" / "ui" / "qml" / "main.qml"
    return Path(__file__).resolve().parent / "qml" / "main.qml"


def build_app() -> tuple[QGuiApplication, QQmlApplicationEngine, WizardState]:
    """Construct the QApplication + QML engine + WizardState. Used by main() and tests."""
    # Install Qt's message handler BEFORE QGuiApplication so any warnings
    # emitted during Qt init (plugin loading, style resolution, etc.) land
    # in our startup.log instead of disappearing into a console=False stderr.
    qInstallMessageHandler(_qt_message_handler)

    # Pin QtQuick.Controls 2 style explicitly. Without this, Qt's autodetect
    # picks Fusion as the fallback default — which we DROP from the frozen
    # bundle (see DROP_BINARIES / DROP_DATAS in astromechos_imager.spec) to
    # save ~5 MB. Basic is the safe cross-platform default; switch to
    # "Windows" if a more native Win32 look is wanted (style binaries are
    # still bundled).
    QQuickStyle.setStyle("Basic")

    # Reuse existing instance if pytest-qt already created one
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.setApplicationName(M["app_title"])
    sys.excepthook = _excepthook

    # Register bundled fonts (Orbitron) so QML can use them by family.
    # Must happen after QGuiApplication exists, before engine.load().
    _load_fonts()

    # Brand the taskbar / window icon — Qt uses this for every top-level
    # window in the process, which matters here because our frameless
    # window has no title bar of its own.
    icon_path = _window_icon_path()
    if icon_path is not None and icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    if getattr(sys, "frozen", False):
        sys.stderr.write(f"[boot] frozen={sys.frozen} MEIPASS={getattr(sys, '_MEIPASS', None)}\n")
        sys.stderr.write(f"[boot] __file__={__file__}\n")
        sys.stderr.write(f"[boot] cwd={os.getcwd()}\n")

    state = WizardState()
    flash_vm = FlashViewModel(state)
    theme = ThemeManager()
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("splashImageUrl", QUrl.fromLocalFile(str(splash_asset_path())))
    ctx.setContextProperty("wizardState", state)
    ctx.setContextProperty("flashViewModel", flash_vm)
    ctx.setContextProperty("theme", theme)
    from astromechos_imager import __version__ as _app_version
    ctx.setContextProperty("appVersion", _app_version)
    engine.flashViewModel = flash_vm   # keepalive
    engine.themeManager = theme         # keepalive

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

    qml_main = _qml_main_path()
    engine.load(QUrl.fromLocalFile(str(qml_main)))
    return app, engine, state


def main() -> int:
    app, _engine, _state = build_app()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
