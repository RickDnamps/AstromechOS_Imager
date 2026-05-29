"""Build the startup screen asset for AstromechOS Imager.

Reads  : images/AstromechOS_Imager.png  (source, any size / mode)
Outputs: astromechos_imager/ui/resources/images/startup_screen_final.png

Processing pipeline
-------------------
1. Normalise source to RGBA.
2. Thumbnail to fit within 800x600 (LANCZOS, aspect-ratio preserving).
3. Paste the thumbnail centred on a solid-black 800x600 canvas. The opaque
   background is intentional — a transparent canvas would render invisible
   when the splash is shown against an undefined backdrop.
4. Save as PNG with optimize=True and no embedded timestamp metadata,
   so repeated runs produce byte-identical output.

No text / copyright overlay — kept as a clean visual asset.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path anchors — all relative to this file's parent (project root)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_IMAGE = PROJECT_ROOT / "images" / "AstromechOS_Imager.png"
OUTPUT_IMAGE = (
    PROJECT_ROOT
    / "astromechos_imager"
    / "ui"
    / "resources"
    / "images"
    / "startup_screen_final.png"
)

CANVAS_W, CANVAS_H = 800, 600
CANVAS_BG = (0, 0, 0, 255)   # opaque black — splash backdrop


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    from PIL import Image

    # 1. Load and normalise source to RGBA
    src = Image.open(SOURCE_IMAGE).convert("RGBA")

    # 2. Thumbnail (in-place resize, aspect-ratio preserving, high quality)
    thumb = src.copy()
    thumb.thumbnail((CANVAS_W, CANVAS_H), Image.LANCZOS)

    # 3. Paste centred on an opaque 800x600 canvas
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), CANVAS_BG)
    x_off = (CANVAS_W - thumb.width) // 2
    y_off = (CANVAS_H - thumb.height) // 2
    canvas.paste(thumb, (x_off, y_off), mask=thumb)

    # 4. Save deterministically (no timestamp metadata)
    OUTPUT_IMAGE.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT_IMAGE, format="PNG", optimize=True)

    print(f"Saved: {OUTPUT_IMAGE}")
    print(f"Size : {OUTPUT_IMAGE.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
