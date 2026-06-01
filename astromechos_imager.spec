# AstromechOS Imager — PyInstaller spec (onedir + aggressive Qt module excludes)
# Produces: dist/AstromechOS Imager/AstromechOS Imager.exe (folder distribution)
#
# Run:  pyinstaller astromechos_imager.spec
#
# vendor/ may be empty in development — the runtime resolves debugfs.exe /
# e2fsck.exe / msys-2.0.dll via sys._MEIPASS and raises a clear error if
# they are missing. See vendor/README.md for how to obtain them.

import fnmatch
from pathlib import Path

PROJECT_ROOT = Path(".").resolve()
QML_DIR = PROJECT_ROOT / "astromechos_imager" / "ui" / "qml"
RES_IMG_DIR = PROJECT_ROOT / "astromechos_imager" / "ui" / "resources" / "images"
RES_FONT_DIR = PROJECT_ROOT / "astromechos_imager" / "ui" / "resources" / "fonts"
VENDOR_DIR = PROJECT_ROOT / "vendor"
ICON_PATH = PROJECT_ROOT / "images" / "AstromechOS_Imager.ico"
MANIFEST_PATH = PROJECT_ROOT / "astromechos_imager_admin.manifest"

# datas: (source, dest_dir) — dest_dir is RELATIVE to bundle root
datas = []
if QML_DIR.exists():
    for p in QML_DIR.rglob("*.qml"):
        datas.append((str(p), "astromechos_imager/ui/qml"))
    # QML JS modules (Theme.js, etc.) — same dest as .qml siblings.
    for p in QML_DIR.rglob("*.js"):
        datas.append((str(p), "astromechos_imager/ui/qml"))
if RES_IMG_DIR.exists():
    for p in RES_IMG_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"}:
            datas.append((str(p), "astromechos_imager/ui/resources/images"))
if RES_FONT_DIR.exists():
    for p in RES_FONT_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in {".ttf", ".otf"}:
            datas.append((str(p), "astromechos_imager/ui/resources/fonts"))
if VENDOR_DIR.exists():
    # Audit Medium #41: ALLOWLIST not denylist. The vendor/ folder is a
    # known set of three Win32 binaries + supporting DLLs. A denylist
    # (skip README / .gitkeep / MISSING_BINARIES) would happily ship a
    # PDB, .bak, license text, or stray dev file the operator dropped in
    # there. Be explicit about what's allowed and warn loudly on anything
    # else so build-time noise catches it before distribution.
    _VENDOR_ALLOWLIST = {
        "debugfs.exe",
        "e2fsck.exe",
        # Native flash core (C ABI, ctypes) — the "tame the shell" layer
        # and (future phases) the raw-write / userspace-FAT engine.
        "astro_flash.dll",
        "msys-2.0.dll",
        # Transitive MSYS2 runtime dependencies needed by debugfs/e2fsck
        "msys-com_err-1.dll",
        "msys-e2p-2.dll",
        "msys-ext2fs-2.dll",
        "msys-ss-2.dll",
        "msys-uuid-1.dll",
        "msys-iconv-2.dll",
        "msys-intl-8.dll",
    }
    _VENDOR_KNOWN_DOCS = {"README.md", ".gitkeep", "MISSING_BINARIES.md"}
    for p in VENDOR_DIR.iterdir():
        if not p.is_file():
            continue
        if p.name in _VENDOR_ALLOWLIST:
            datas.append((str(p), "vendor"))
        elif p.name in _VENDOR_KNOWN_DOCS:
            continue   # explicitly skipped
        else:
            print(
                f"[spec] WARNING: vendor/{p.name} is not in the allowlist "
                f"— refusing to ship. Add it to _VENDOR_ALLOWLIST if "
                f"intentional, otherwise remove the file."
            )

FIRSTBOOT_SNAPSHOT = PROJECT_ROOT / "tests" / "contract" / "fixtures" / "firstboot_setup.sh.snapshot"
if FIRSTBOOT_SNAPSHOT.is_file():
    datas.append((str(FIRSTBOOT_SNAPSHOT), "tests/contract/fixtures"))

# Window icon (.ico) — also embedded in the EXE for the file icon, but
# needs to live in the bundle so QGuiApplication.setWindowIcon() can find
# it at runtime to brand the taskbar.
if ICON_PATH.is_file():
    datas.append((str(ICON_PATH), "images"))

# ── Aggressive excludes — Qt modules we do NOT use ─────────────────────────
# These contribute hundreds of MB combined. PyInstaller's PySide6 hook pulls
# the entire Qt distribution by default; we whittle it down to just the
# QtQml/QtQuick/QtQuickControls2 surface that main.qml actually needs.
qt_excludes = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    # NOTE: do NOT exclude PySide6.QtNetwork — PySide6.QtQml depends on it
    # transitively (QML XHR, Image network sources, etc.). Excluding it makes
    # `from PySide6.QtQml import QQmlApplicationEngine` raise ImportError at
    # startup and the GUI dies with a PyInstaller popup.
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    # NOTE: do NOT exclude PySide6.QtOpenGL — PySide6.QtQuick imports it at
    # top-level (confirmed via PyInstaller warn-*.txt). Excluding it makes
    # QML loading silently fail (no window, process stays alive idle).
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "PySide6.QtXml",
]

stdlib_excludes = [
    "tkinter",
    "test",
    "unittest",
    "pydoc_data",
    "lib2to3",
    "pickletools",
]

block_cipher = None

a = Analysis(
    ["astromechos_imager/ui/app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "astromechos_imager.core.imagesource",
        "astromechos_imager.core.diskwriter",
        "astromechos_imager.core.orchestrator",
        "astromechos_imager.core.bootpartition",
        "astromechos_imager.core.rootfs",
        "astromechos_imager.core.rootfs_personalizer",
        "astromechos_imager.platform.windows",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=qt_excludes + stdlib_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


# ── Post-Analysis binary/data filter ──────────────────────────────────────
# PyInstaller's PySide6 hook is comprehensive: it bundles every Qt6*.dll and
# every PySide6/qml/* module unconditionally, regardless of `excludes=`.
# `excludes` only blocks Python BINDING modules (~100 KB each); the heavy
# native DLLs (Qt6WebEngineCore.dll alone is 145 MB) come through.
# This filter runs after Analysis() and trims a.binaries + a.datas by glob
# pattern on the destination path. Test by running the rebuilt exe and
# watching %LOCALAPPDATA%/AstromechOS_Imager/startup.log — any missing-
# resource warning means a pattern below was too aggressive.

def _filter_entries(entries, drop_patterns, keep_patterns=()):
    """Filter PyInstaller (dest, src, kind) tuples by glob on dest.
    keep_patterns wins over drop_patterns (whitelist override).
    Returns (kept_entries, bytes_dropped, dropped_count)."""
    kept, dropped_bytes, dropped_count = [], 0, 0
    for entry in entries:
        dest = entry[0].replace("\\", "/")
        if any(fnmatch.fnmatch(dest, k) for k in keep_patterns):
            kept.append(entry)
            continue
        if any(fnmatch.fnmatch(dest, p) for p in drop_patterns):
            try:
                dropped_bytes += Path(entry[1]).stat().st_size
            except OSError:
                pass
            dropped_count += 1
            continue
        kept.append(entry)
    return kept, dropped_bytes, dropped_count


DROP_BINARIES = [
    # WebEngine (embedded Chromium) — single biggest win, ~145 MB.
    "PySide6/Qt6WebEngine*.dll",
    "PySide6/QtWebEngineProcess.exe",
    "PySide6/resources/qtwebengine_*",
    # Software OpenGL fallback (~20 MB) — virtually every modern Windows
    # install has hardware acceleration; the Mesa fallback is dead weight.
    "PySide6/opengl32sw.dll",
    # Qt 3D family — never used (no 3D scenes in QML).
    "PySide6/Qt63D*.dll",
    "PySide6/Qt6Quick3D*.dll",
    # Charts / data visualization.
    "PySide6/Qt6Charts*.dll",
    "PySide6/Qt6DataVisualization*.dll",
    "PySide6/Qt6Graphs.dll",
    # Multimedia / spatial audio — no audio/video playback in the imager.
    "PySide6/Qt6Multimedia*.dll",
    "PySide6/Qt6SpatialAudio.dll",
    # PDF rendering.
    "PySide6/Qt6Pdf*.dll",
    # Location / positioning.
    "PySide6/Qt6Location.dll",
    "PySide6/Qt6Positioning*.dll",
    # Sensors, serial bus, bluetooth, NFC — irrelevant to a SD-card flasher.
    "PySide6/Qt6Sensors*.dll",
    "PySide6/Qt6SerialBus.dll",
    "PySide6/Qt6SerialPort.dll",
    # SQL backend, TTS, virtual keyboard.
    "PySide6/Qt6Sql.dll",
    "PySide6/Qt6TextToSpeech.dll",
    "PySide6/Qt6VirtualKeyboard*.dll",
    # Web protocols (other than QtNetwork, which QtQml needs).
    "PySide6/Qt6WebChannel*.dll",
    "PySide6/Qt6WebSockets.dll",
    "PySide6/Qt6WebView*.dll",
    # Remote objects / Scxml.
    "PySide6/Qt6RemoteObjects*.dll",
    "PySide6/Qt6Scxml*.dll",
    # Qt Test infrastructure shouldn't ship to end users.
    "PySide6/Qt6Test.dll",
    "PySide6/Qt6QuickTest.dll",
    # Alternative QtQuick.Controls 2 styles — we keep Basic + Windows.
    "PySide6/Qt6QuickControls2Fusion*.dll",
    "PySide6/Qt6QuickControls2Imagine*.dll",
    "PySide6/Qt6QuickControls2Material*.dll",
    "PySide6/Qt6QuickControls2Universal*.dll",
]

DROP_DATAS = [
    # Whole QML module trees we don't import.
    "PySide6/qml/Qt3D/*",
    "PySide6/qml/QtCharts/*",
    "PySide6/qml/QtDataVisualization/*",
    "PySide6/qml/QtGraphs/*",
    "PySide6/qml/QtLocation/*",
    "PySide6/qml/QtMultimedia/*",
    "PySide6/qml/QtPositioning/*",
    "PySide6/qml/QtQuick3D/*",
    "PySide6/qml/QtRemoteObjects/*",
    "PySide6/qml/QtScxml/*",
    "PySide6/qml/QtSensors/*",
    "PySide6/qml/QtTest/*",
    "PySide6/qml/QtTextToSpeech/*",
    "PySide6/qml/QtWebChannel/*",
    "PySide6/qml/QtWebEngine/*",
    "PySide6/qml/QtWebSockets/*",
    # Alternative Quick.Controls 2 styles.
    "PySide6/qml/QtQuick/Controls/Fusion/*",
    "PySide6/qml/QtQuick/Controls/Imagine/*",
    "PySide6/qml/QtQuick/Controls/Material/*",
    "PySide6/qml/QtQuick/Controls/Universal/*",
    "PySide6/qml/QtQuick/Controls/macOS/*",
    "PySide6/qml/QtQuick/Controls/iOS/*",
    # Drop ALL Qt translations except the four whitelisted below.
    "PySide6/translations/*.qm",
]

KEEP_DATAS = [
    "PySide6/translations/qt_en.qm",
    "PySide6/translations/qt_fr.qm",
    "PySide6/translations/qtbase_en.qm",
    "PySide6/translations/qtbase_fr.qm",
]


a.binaries, _bin_bytes, _bin_count = _filter_entries(a.binaries, DROP_BINARIES)
a.datas, _data_bytes, _data_count = _filter_entries(a.datas, DROP_DATAS, KEEP_DATAS)
print(
    f"[spec] Trimmed {_bin_count} binaries (-{_bin_bytes/1024/1024:.1f} MB) "
    f"and {_data_count} data files (-{_data_bytes/1024/1024:.1f} MB)"
)


pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── ONEDIR mode — fast cold launch (no decompress step), AV-friendly ─────
# Distribution = `dist/AstromechOS Imager/` folder. ZIP it for transport.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,    # binaries go side-by-side, NOT inside exe
    name="AstromechOS Imager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    # uac_admin=True is the RELIABLE way to make PyInstaller stamp the
    # bootloader's manifest with requestedExecutionLevel=requireAdministrator.
    # Passing only `manifest=<file>` did NOT take effect — the built exe ended
    # up with the default `asInvoker` level, so on a normal double-click the
    # app ran UN-elevated and every privileged Win32 call (CreateFileW on
    # \\.\PHYSICALDRIVEn for write, DeleteVolumeMountPointW, FSCTL_*) failed
    # with ERROR_ACCESS_DENIED (errno 5) — the SD never got written. With
    # uac_admin the OS shows the UAC prompt at launch and the process is
    # elevated, so raw-disk access is permitted.
    uac_admin=True,
    manifest=str(MANIFEST_PATH) if MANIFEST_PATH.is_file() else None,
    icon=str(ICON_PATH) if ICON_PATH.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AstromechOS Imager",
)
