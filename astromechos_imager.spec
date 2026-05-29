# AstromechOS Imager — PyInstaller spec
# Produces: dist/AstromechOS Imager.exe
#
# Run:  pyinstaller astromechos_imager.spec
#
# Requires vendor/ to be populated before building.
# See vendor/README.md for details.

from pathlib import Path

QML_DIR = Path("astromechos_imager/ui/qml")
VENDOR_DIR = Path("vendor")

datas = [
    *[(str(p), str(QML_DIR.parent / p.parent.name / p.name))
      for p in QML_DIR.rglob("*.qml")] if QML_DIR.exists() else [],
    *[(str(p), "vendor") for p in VENDOR_DIR.glob("*")
      if p.is_file() and p.name != "README.md"],
]

block_cipher = None

a = Analysis(
    ["astromechos_imager/ui/app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickControls2"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="AstromechOS Imager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    manifest="astromechos_imager_admin.manifest",
    icon=None,
)
