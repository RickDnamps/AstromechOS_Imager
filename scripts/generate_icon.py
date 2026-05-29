"""Generate images/AstromechOS_Imager.ico with proper square multi-resolution.

Draws a minimalist R2-D2 silhouette matching the QML R2HeadIcon line-art
language: techno cyan-teal accent on a deep-dark rounded square. Output
is a Windows .ico bundling 16, 24, 32, 48, 64, 128, 256 px PNGs.

Run:  .venv/Scripts/python.exe scripts/generate_icon.py
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "images" / "AstromechOS_Imager.ico"

# Theme colors (must stay in sync with qml/Theme.js)
BG_DARK   = (12, 16, 20, 255)        # #0c1014
ACCENT    = (61, 212, 196, 255)      # #3dd4c4 — cyan-teal
ACCENT_DIM = (42, 140, 128, 255)     # #2a8c80


def render(size: int) -> Image.Image:
    """Return one square PNG frame at the requested edge length."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    # Rounded-square dark background tile — fills the icon body so the
    # silhouette is legible on light Windows themes too.
    pad = max(1, size // 32)
    radius = max(2, size // 6)
    d.rounded_rectangle(
        [(pad, pad), (size - pad, size - pad)],
        radius=radius,
        fill=BG_DARK,
        outline=ACCENT,
        width=max(1, size // 64),
    )

    # ── R2 silhouette — dome + body, filled cyan-teal. ───────────────
    # Geometry scaled to a virtual 100x100 then mapped to size.
    s = size / 100.0
    def p(x, y): return (round(x * s), round(y * s))

    # Body box.
    d.rectangle([p(34, 50), p(66, 84)], fill=ACCENT)
    # Dome — half ellipse on top.
    d.chord([p(34, 30), p(66, 62)], 180, 360, fill=ACCENT)
    # Two internal data bands cut out of the body — punched with bg color
    # for a "line-art" feel.
    band_h = max(1, round(2 * s))
    d.rectangle([p(40, 60), p(60, 60 + band_h * 50 / size)], fill=BG_DARK)
    d.rectangle([p(40, 70), p(60, 70 + band_h * 50 / size)], fill=BG_DARK)

    # Eye lens on the dome.
    eye_r = max(1, round(3 * s))
    cx, cy = p(50, 42)
    d.ellipse([(cx - eye_r, cy - eye_r), (cx + eye_r, cy + eye_r)], fill=BG_DARK)
    d.ellipse(
        [(cx - eye_r + max(1, eye_r // 3), cy - eye_r + max(1, eye_r // 3)),
         (cx + eye_r - max(1, eye_r // 3), cy + eye_r - max(1, eye_r // 3))],
        fill=ACCENT,
    )

    return img


def main() -> None:
    # Render the largest size sharply, let PIL downsample for the smaller
    # frames. Hand-rendering each size would be cleaner but Pillow's ICO
    # writer always picks frame[0] from append_images and then resizes —
    # the sizes argument is more reliable.
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master = render(256)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    master.save(OUT, format="ICO", sizes=sizes)
    print(f"Wrote {OUT} with sizes {[s[0] for s in sizes]}")


if __name__ == "__main__":
    main()
