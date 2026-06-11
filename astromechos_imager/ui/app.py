"""QApplication entry point + crash hook for AstromechOS Imager."""
from __future__ import annotations

import faulthandler
import logging
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

from astromechos_imager.logging_setup.jsonl_formatter import setup_logging
from astromechos_imager.ui.flash_view_model import FlashViewModel
from astromechos_imager.ui.messages import M
from astromechos_imager.ui.theme_manager import ThemeManager
from astromechos_imager.ui.wizard_state import WizardState


_QT_MSG_LEVEL = {
    QtMsgType.QtDebugMsg: "DEBUG",
    QtMsgType.QtInfoMsg: "INFO",
    QtMsgType.QtWarningMsg: "WARN",
    QtMsgType.QtCriticalMsg: "CRIT",
    QtMsgType.QtFatalMsg: "FATAL",
}


# Benign transient QML warnings, suppressed to keep the log readable: theme
# context bindings briefly re-evaluated during StackView transitions, and a
# layout rearrange notice (harmless).
_QT_NOISE = (
    "Cannot read property 'colors' of null",
    "Detected recursive rearrange",
)


def _qt_message_handler(msg_type, ctx, message) -> None:
    # Drop Qt's own debug chatter and known-benign transient warnings.
    if msg_type == QtMsgType.QtDebugMsg:
        return
    if any(noise in message for noise in _QT_NOISE):
        return
    sink = sys.stderr if sys.stderr is not None else sys.__stderr__
    if sink is None:
        return
    level = _QT_MSG_LEVEL.get(msg_type, "?")
    where = f" ({ctx.file}:{ctx.line})" if ctx and ctx.file else ""
    sink.write(f"[Qt {level}]{where} {message}\n")


def _excepthook(exc_type, exc_value, tb) -> None:
    """Last-resort crash logger for uncaught exceptions."""
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
    # On Windows, suppress the shell's "Le volume ne contient pas de
    # système de fichiers connu" / "Format K:?" pop-ups that fire when
    # we read or write a removable device mid-flash. Without this our
    # raw-write phase reliably triggers a modal Explorer dialog the
    # moment USB PnP polls the disk — the dialog steals focus, locks
    # the volume, and the customize step then dies with
    # FileNotFoundError(errno=2). SetErrorMode is process-inherited so
    # both the GUI and any subprocess we spawn benefit. Must run before
    # QGuiApplication so the flag is in force during plugin init too.
    # True = automount is OFF for the session (or N/A off-Windows); False =
    # mountvol /N failed (non-elevated run) and pop-ups can still fire.
    _automount_defense_active = True
    _session_guard = None
    if sys.platform == "win32":
        try:
            from astromechos_imager.platform.windows import (
                _suppress_shell_error_dialogs_for_process,
            )
            _suppress_shell_error_dialogs_for_process()
        except Exception:
            pass  # non-fatal — pop-ups will still appear, that's all
        # Explicit AppUserModelID so the Windows taskbar binds OUR custom .ico
        # to this process. Without it the taskbar falls back to the host
        # python/bootloader's generic icon (and won't group our window).
        # Must run before the first top-level window is created.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "AstromechOS.Imager.1"
            )
        except Exception:
            pass
        # If a previous run crashed mid-flash with automount disabled, re-enable
        # it now (crash-safe restore of the Windows auto-mount setting), then
        # immediately disable automount for THIS app session.
        #
        # Bug fix 2026-06-11 (field: K: visible in Explorer + "Format?" popup
        # while flashing the MASTER): FlashJob only disabled automount when the
        # operator clicked Flash — but the wizard tells the operator to INSERT
        # the cards earlier (Step 4), while automount was still ON. Windows
        # assigned the letter (and persisted the volume↔letter binding in
        # MountedDevices) at insertion, before any FlashJob defense ran.
        # Disabling at app launch closes that window: a card inserted at ANY
        # point of the wizard never gets a drive letter, so Explorer has
        # nothing to render, probe, or pop a format dialog against.
        # Restore points unchanged: aboutToQuit below + the crash marker.
        # The AutomountSessionGuard owns the {mutex, marker, automount}
        # triple: it claims the single-instance mutex FIRST, so a present
        # marker can only mean a genuinely crashed session (a second live
        # instance no longer runs mountvol /E under the first one's feet).
        try:
            from astromechos_imager.platform.session_guard import (
                AutomountSessionGuard,
            )
            from astromechos_imager.platform.windows import is_elevated
            _session_guard = AutomountSessionGuard()
            _automount_defense_active = _session_guard.acquire()
            if _session_guard.already_running:
                # Another live instance owns the automount session — touching
                # it here would disarm that instance mid-flash (audit A4).
                # Native MessageBox: Qt does not exist yet at this point.
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None,
                    "AstromechOS Imager is already running.\n\n"
                    "Close the other window first.",
                    "AstromechOS Imager",
                    0x30,  # MB_ICONWARNING
                )
                sys.exit(0)
            if not _automount_defense_active:
                logging.getLogger(__name__).warning(
                    "automount defense NOT armed (mountvol /N failed; "
                    "elevated=%s) — run as administrator to suppress "
                    "Windows format pop-ups", is_elevated(),
                )
        except SystemExit:
            raise
        except Exception:
            logging.getLogger(__name__).exception("session guard failed")
            _automount_defense_active = False
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

    # Restore Windows automount when the app closes. It is disabled for the
    # ENTIRE flashing session (disabled at launch by the session guard, never
    # re-enabled per-card) so Windows can't auto-mount + probe a
    # freshly-inserted card mid-session — notably the Slave — and pop
    # "Format this disk?". This is the single normal-exit restore point; a
    # crash is covered by the marker file + the guard's repair on the next
    # launch. The guard also holds the named mutex the Inno Setup installer
    # checks (AppMutex=Global\AstromechOS_Imager_AppMutex, Audit High #21) —
    # stashing it on app keeps the handle alive for the process lifetime.
    if sys.platform == "win32":
        if _session_guard is not None:
            setattr(app, "_session_guard", _session_guard)
            app.aboutToQuit.connect(lambda: _session_guard.release())
        else:
            # Guard construction failed — fall back to a best-effort direct
            # restore so a session that DID manage to disable automount
            # never leaves the machine without its USB drives.
            try:
                from astromechos_imager.platform.windows import enable_automount
                app.aboutToQuit.connect(lambda: enable_automount())
            except Exception:
                pass

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
        # Audit High #20: when the startup-log open above failed (disk full,
        # ACL denied), sys.stderr stays None and an unconditional write here
        # would raise AttributeError BEFORE the QML window appears —
        # exactly the symptom the log was meant to diagnose. Guard via the
        # same fallback pattern as _qt_message_handler.
        sink = sys.stderr if sys.stderr is not None else sys.__stderr__
        if sink is not None:
            sink.write(f"[boot] frozen={sys.frozen} MEIPASS={getattr(sys, '_MEIPASS', None)}\n")
            sink.write(f"[boot] __file__={__file__}\n")
            sink.write(f"[boot] cwd={os.getcwd()}\n")

    # Windows: when the operator SELECTS a target card (wizard Step 4), kill
    # its drive letter(s) immediately. Covers the card-inserted-BEFORE-launch
    # case that automount-off cannot (automount only blocks NEW mounts).
    # Selection is the earliest moment the TARGET disk is known — doing this
    # at launch would also detach the operator's SSD/USB sticks. Injected as
    # a callable so WizardState stays platform-free and unit tests (which
    # call the drive-id setters with arbitrary ids) never touch real disks.
    release_letters = None
    if sys.platform == "win32":
        def release_letters(drive_id: int) -> None:
            from astromechos_imager.platform.windows import (  # noqa: PLC0415
                force_unmount_letter,
                letters_on_disk,
            )
            letters = letters_on_disk(drive_id)
            for letter in letters:
                force_unmount_letter(letter)
            if letters:
                logging.getLogger(__name__).info(
                    "selection: released letter(s) %s on disk %s",
                    letters, drive_id)

    state = WizardState(release_disk_letters=release_letters)
    flash_vm = FlashViewModel(state)
    theme = ThemeManager()
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("splashImageUrl", QUrl.fromLocalFile(str(splash_asset_path())))
    ctx.setContextProperty("wizardState", state)
    ctx.setContextProperty("flashViewModel", flash_vm)
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("automountDefenseActive", _automount_defense_active)
    from astromechos_imager import __version__ as _app_version
    ctx.setContextProperty("appVersion", _app_version)
    engine.flashViewModel = flash_vm   # keepalive
    engine.themeManager = theme         # keepalive

    # Drive list model — Windows-only; tests inject their own. Declared as a
    # null placeholder BEFORE engine.load() so QML bindings resolve (Step 3 /
    # Step 5 guard `driveListModel ? …`). The REAL model — and its blocking
    # WMI/COM first refresh — is brought up 200 ms into the event loop: a
    # singleShot(0) fires on the FIRST loop iteration, i.e. typically before
    # the first frame has presented, so the WMI query would block the thread
    # before anything is on screen. 200 ms lets the splash paint first.
    ctx.setContextProperty("driveListModel", None)

    qml_main = _qml_main_path()
    engine.load(QUrl.fromLocalFile(str(qml_main)))

    if sys.platform == "win32":
        from PySide6.QtCore import QTimer

        def _bring_up_drive_model() -> None:
            # Audit Medium #36: log failures (don't silently swallow) so a
            # blank Step 3 is distinguishable from "no card / WMI broken".
            # setContextProperty on the already-declared key refreshes the
            # QML bindings that reference driveListModel.
            try:
                from astromechos_imager.platform.windows import WindowsPlatformIO
                from astromechos_imager.ui.drive_list_model import DriveListModel
                drive_model = DriveListModel(WindowsPlatformIO())
                drive_model.start_polling()
                ctx.setContextProperty("driveListModel", drive_model)
                engine.driveListModel = drive_model   # keepalive

                # Strip the drive letters of every NON-suspect candidate, now
                # and on every list change. Cards inserted BEFORE launch kept
                # their letters (automount-off only blocks NEW mounts), and a
                # crashed-session repair (mountvol /E) may have just remounted
                # one — a lettered RAW/ext4 volume is what Explorer/WmiPrvSE
                # probe and answer with "Format this disk?" (audit defect A1).
                # USB FIXED disks (external SSDs) are never auto-touched.
                # Win32 calls run on a daemon thread (COM-free helpers), and
                # re-stripping an already-letterless disk is a cheap no-op.
                import threading

                def _strip_candidate_letters() -> None:
                    ids = drive_model.strippable_drive_ids()
                    if not ids:
                        return

                    def work() -> None:
                        for drive_id in ids:
                            try:
                                release_letters(drive_id)
                            except Exception:
                                logging.getLogger(__name__).exception(
                                    "letter strip failed for drive %s",
                                    drive_id,
                                )

                    threading.Thread(
                        target=work, name="strip-letters", daemon=True
                    ).start()

                _strip_candidate_letters()
                drive_model.countChanged.connect(_strip_candidate_letters)

                # CRITICAL: pause the WMI poll while a flash is in flight.
                # refresh() runs Win32_DiskDrive + ASSOCIATORS queries ON THE
                # MAIN THREAD every 2 s. During a flash the target disk is
                # dismounted / layout-deleted / RAW / locked, and a WMI
                # ASSOCIATORS query against a RAW disk can BLOCK for seconds
                # inside the storage stack — freezing the UI thread so the
                # screen never advances past "validating" to "Writing…" and
                # progress signals from the worker thread pile up undelivered.
                # The write itself keeps running (worker thread, IOCTL, no COM),
                # so the operator sees a frozen UI over a healthy flash and
                # cancels it. Stop polling for verifying+flashing, resume when
                # idle/done/error/cancelled.
                def _sync_drive_polling() -> None:
                    try:
                        # "cancelling" included (audit R2): cancel() flips the
                        # status immediately while the worker is still running
                        # its cleanup (diskpart exFAT restore on a RAW disk) —
                        # resuming the WMI poll there races diskpart and can
                        # block the UI thread for seconds.
                        if flash_vm.status in (
                                "verifying", "flashing", "cancelling"):
                            drive_model.stop_polling()
                        else:
                            drive_model.start_polling()
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "drive-poll sync failed"
                        )

                flash_vm.statusChanged.connect(_sync_drive_polling)
            except Exception:
                logging.getLogger(__name__).exception(
                    "DriveListModel bring-up failed — Step 3 will be empty"
                )

        QTimer.singleShot(200, _bring_up_drive_model)

    return app, engine, state


def main() -> int:
    # Wire the JSONL session logger BEFORE build_app() so any exception
    # raised during Qt/QML construction is captured in
    # %APPDATA%\AstromechOS Imager\logs\flash-*.log. If setup_logging itself
    # raises (disk full, ACL denied), don't prevent launch — the frozen
    # stderr redirect at module top is still a safety net.
    try:
        setup_logging()
    except Exception:
        logging.exception("setup_logging() failed — continuing without JSONL session log")
    app, _engine, _state = build_app()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
