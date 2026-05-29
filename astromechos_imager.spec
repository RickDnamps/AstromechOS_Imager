# AstromechOS Imager — PyInstaller spec (onedir + aggressive Qt module excludes)
# Produces: dist/AstromechOS Imager/AstromechOS Imager.exe (folder distribution)
#
# Run:  pyinstaller astromechos_imager.spec
#
# vendor/ may be empty in development — the runtime resolves debugfs.exe /
# e2fsck.exe / msys-2.0.dll via sys._MEIPASS and raises a clear error if
# they are missing. See vendor/README.md for how to obtain them.

from pathlib import Path

PROJECT_ROOT = Path(".").resolve()
QML_DIR = PROJECT_ROOT / "astromechos_imager" / "ui" / "qml"
RES_IMG_DIR = PROJECT_ROOT / "astromechos_imager" / "ui" / "resources" / "images"
VENDOR_DIR = PROJECT_ROOT / "vendor"
ICON_PATH = PROJECT_ROOT / "images" / "AstromechOS_Imager.ico"
MANIFEST_PATH = PROJECT_ROOT / "astromechos_imager_admin.manifest"

# datas: (source, dest_dir) — dest_dir is RELATIVE to bundle root
datas = []
if QML_DIR.exists():
    for p in QML_DIR.rglob("*.qml"):
        datas.append((str(p), "astromechos_imager/ui/qml"))
if RES_IMG_DIR.exists():
    for p in RES_IMG_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"}:
            datas.append((str(p), "astromechos_imager/ui/resources/images"))
if VENDOR_DIR.exists():
    for p in VENDOR_DIR.iterdir():
        if p.is_file() and p.name not in {"README.md", ".gitkeep", "MISSING_BINARIES.md"}:
            datas.append((str(p), "vendor"))

FIRSTBOOT_SNAPSHOT = PROJECT_ROOT / "tests" / "contract" / "fixtures" / "firstboot_setup.sh.snapshot"
if FIRSTBOOT_SNAPSHOT.is_file():
    datas.append((str(FIRSTBOOT_SNAPSHOT), "tests/contract/fixtures"))

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
