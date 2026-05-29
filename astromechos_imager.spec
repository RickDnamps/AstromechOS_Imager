# AstromechOS Imager — PyInstaller spec
# Produces: dist/AstromechOS Imager.exe
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

# PyInstaller datas format: list of (source_path, dest_dir) tuples.
# dest_dir is RELATIVE to the bundle root; PyInstaller places the file at
# <bundle_root>/<dest_dir>/<basename_of_source>.
datas = []

# QML files → <bundle>/astromechos_imager/ui/qml/<file>.qml
if QML_DIR.exists():
    for p in QML_DIR.rglob("*.qml"):
        datas.append((str(p), "astromechos_imager/ui/qml"))

# UI resource images (splash, future icons) → <bundle>/astromechos_imager/ui/resources/images/<file>
if RES_IMG_DIR.exists():
    for p in RES_IMG_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"}:
            datas.append((str(p), "astromechos_imager/ui/resources/images"))

# Vendor binaries (debugfs.exe, e2fsck.exe, msys-2.0.dll) → <bundle>/vendor/<file>
# Skipped silently if vendor/ is empty — the runtime will raise an explicit
# RuntimeError if a feature that needs them is invoked.
if VENDOR_DIR.exists():
    for p in VENDOR_DIR.iterdir():
        if p.is_file() and p.name not in {"README.md", ".gitkeep"}:
            datas.append((str(p), "vendor"))

# Contract drift fixture (in case the running .exe wants to self-check)
FIRSTBOOT_SNAPSHOT = PROJECT_ROOT / "tests" / "contract" / "fixtures" / "firstboot_setup.sh.snapshot"
if FIRSTBOOT_SNAPSHOT.is_file():
    datas.append((str(FIRSTBOOT_SNAPSHOT), "tests/contract/fixtures"))

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
        # Core modules pulled in by the CLI fallback / runtime resolvers
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
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AstromechOS Imager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    manifest=str(MANIFEST_PATH) if MANIFEST_PATH.is_file() else None,
    icon=str(ICON_PATH) if ICON_PATH.is_file() else None,
)
