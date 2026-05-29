"""Build the startup screen asset for AstromechOS Imager.

Reads  : images/AstromechOS_Imager.png  (source, any size / mode)
Outputs: astromechos_imager/ui/resources/images/startup_screen_final.png

Processing pipeline
-------------------
1.  Normalise source to RGBA.
2.  Thumbnail to fit within 800x600 (LANCZOS, aspect-ratio preserving).
3.  Paste the thumbnail centred on a transparent 800x600 RGBA canvas.
4.  Render a three-line copyright block, bottom-centre:
      Line 1  "AstromechOS © 2026"      bold-ish, ~14 pt
      Line 2  "GNU GPL v3"              regular,  ~11 pt
      Line 3  "Distributed Startup Software"  regular, ~11 pt
    Text colour: (200, 200, 200, 220) — light-grey, semi-opaque,
    readable over both dark and mid-tone background pixels.
    8 px inter-line gap; 16 px below last line to canvas bottom.
5.  Save as PNG with optimize=True and no embedded timestamp metadata,
    so repeated runs produce byte-identical output.

Font search order (Windows): arial.ttf → segoeui.ttf → PIL default.
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

# Copyright block content — spelling is critical: AstromechOS (capital A + OS)
COPYRIGHT_LINES = [
    ("AstromechOS © 2026", 14),   # Line 1: bold-ish, 14 pt equiv
    ("GNU GPL v3", 11),                # Line 2: regular, 11 pt equiv
    ("Distributed Startup Software", 11),  # Line 3: regular, 11 pt equiv
]

TEXT_COLOR = (200, 200, 200, 220)   # light-grey, semi-opaque
LINE_GAP = 8                         # pixels between lines
BOTTOM_PAD = 16                      # pixels from last line baseline to canvas bottom


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------
def _load_font(size: int):
    """Return a PIL font at *size* points, falling back to the built-in default."""
    from PIL import ImageFont

    windows_fonts = Path(r"C:\Windows\Fonts")
    candidates = ["arial.ttf", "segoeui.ttf"]
    for name in candidates:
        candidate = windows_fonts / name
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                continue
    # Fall back to PIL's built-in bitmap font (no size argument supported)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    from PIL import Image, ImageDraw

    # 1. Load and normalise source to RGBA
    src = Image.open(SOURCE_IMAGE).convert("RGBA")

    # 2. Thumbnail (in-place resize, aspect-ratio preserving, high quality)
    thumb = src.copy()
    thumb.thumbnail((CANVAS_W, CANVAS_H), Image.LANCZOS)

    # 3. Paste centred on a transparent 800x600 canvas
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    x_off = (CANVAS_W - thumb.width) // 2
    y_off = (CANVAS_H - thumb.height) // 2
    canvas.paste(thumb, (x_off, y_off), mask=thumb)

    # 4. Render copyright block
    draw = ImageDraw.Draw(canvas)

    # Pre-load fonts for each line
    fonts = [_load_font(pt) for _, pt in COPYRIGHT_LINES]

    # Measure each line so we can position it precisely
    line_sizes: list[tuple[int, int]] = []
    for (text, _), font in zip(COPYRIGHT_LINES, fonts):
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            # Older Pillow without textbbox — use textsize
            w, h = draw.textsize(text, font=font)  # type: ignore[attr-defined]
        line_sizes.append((w, h))

    # Total block height
    total_h = sum(h for _, h in line_sizes) + LINE_GAP * (len(COPYRIGHT_LINES) - 1)

    # Bottom anchor: baseline of last line sits BOTTOM_PAD px above canvas bottom
    block_bottom = CANVAS_H - BOTTOM_PAD
    block_top = block_bottom - total_h

    # Draw each line centred horizontally
    y_cursor = block_top
    for (text, _), font, (w, h) in zip(COPYRIGHT_LINES, fonts, line_sizes):
        x = (CANVAS_W - w) // 2
        draw.text((x, y_cursor), text, font=font, fill=TEXT_COLOR)
        y_cursor += h + LINE_GAP

    # 5. Save deterministically (no timestamp metadata)
    OUTPUT_IMAGE.parent.mkdir(parents=True, exist_ok=True)

    # Strip PNG metadata that varies between runs (e.g., creation time).
    # Saving via PIL with these settings produces stable output.
    canvas.save(
        OUTPUT_IMAGE,
        format="PNG",
        optimize=True,
        # PIL does not embed a creation timestamp by default; explicitly pass
        # no pnginfo to ensure nothing varies between runs.
    )

    print(f"Saved: {OUTPUT_IMAGE}")
    print(f"Size : {OUTPUT_IMAGE.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
