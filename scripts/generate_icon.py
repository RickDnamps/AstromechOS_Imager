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
BG_DARK = (16, 20, 24, 255)         # #101418
ACCENT  = (94, 155, 214, 255)       # #5e9bd6 — R2 piloting cyan-blue


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

    # ── R2 silhouette ────────────────────────────────────────────────
    # Geometry scaled to a virtual 100x100 grid then mapped to `size`.
    s = size / 100.0
    def p(x, y): return (round(x * s), round(y * s))

    # Dome (half-ellipse, convex up).
    d.chord([p(30, 26), p(70, 58)], 180, 360, fill=ACCENT)

    # Body box.
    d.rectangle([p(32, 42), p(68, 78)], fill=ACCENT)

    # Two data-band stripes cut out of the body.
    d.rectangle([p(40, 52), p(60, 54)], fill=BG_DARK)
    d.rectangle([p(40, 64), p(60, 66)], fill=BG_DARK)

    # Eye lens — dark rounded rectangle on the dome.
    # Use rounded_rectangle so the lens is recognizable at small sizes.
    lens = [p(38, 32), p(62, 40)]
    d.rounded_rectangle(lens, radius=max(1, round(3 * s)), fill=BG_DARK)
    # Pupil inside the lens.
    d.rounded_rectangle([p(45, 34), p(55, 38)], radius=max(1, round(1 * s)), fill=ACCENT)

    # Legs — angled lines from the body bottom outward.
    leg_w = max(1, round(2.4 * s))
    d.line([p(38, 78), p(34, 90)], fill=ACCENT, width=leg_w)
    d.line([p(62, 78), p(66, 90)], fill=ACCENT, width=leg_w)
    # Feet — short horizontal caps.
    d.line([p(31, 90), p(38, 90)], fill=ACCENT, width=leg_w)
    d.line([p(62, 90), p(69, 90)], fill=ACCENT, width=leg_w)

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
