"""Build the Windows .ico file for AstromechOS Imager.

Reads  : images/AstromechOS_Imager.png  (source)
Outputs: images/AstromechOS_Imager.ico   (Windows icon, multi-size)

The .ico is embedded into the PyInstaller bundle via astromechos_imager.spec.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT_ROOT / "images" / "AstromechOS_Imager.png"
OUTPUT = PROJECT_ROOT / "images" / "AstromechOS_Imager.ico"
SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    from PIL import Image
    src = Image.open(SOURCE).convert("RGBA")
    # PIL handles multi-size ICO when you pass sizes=
    src.save(OUTPUT, format="ICO", sizes=SIZES)
    print(f"Saved: {OUTPUT}")
    print(f"Size : {OUTPUT.stat().st_size:,} bytes")
    print(f"Sub-icons: {SIZES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
