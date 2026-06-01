"""Analyze the captured splash screenshot for border bands + content bounds."""
import sys
from pathlib import Path
from PIL import Image

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("screenshots/dark/00-splash.png")
im = Image.open(p).convert("RGB")
W, H = im.size
px = im.load()
print(f"screenshot: {W}x{H} ratio={W/H:.3f}  file={p}")


def row_uniform(y, tol=8):
    c0 = px[W // 2, y]
    for x in range(0, W, 30):
        c = px[x, y]
        if any(abs(c[k] - c0[k]) > tol for k in range(3)):
            return False
    return True


top = 0
while top < H and row_uniform(top):
    top += 1
bot = H - 1
while bot > 0 and row_uniform(bot):
    bot -= 1

print(f"top uniform band: {top}px  color={px[W//2, 0]}")
print(f"bottom uniform band: {H - 1 - bot}px  color={px[W//2, H-1]}")
print(f"non-uniform (image) rows: {top}..{bot} = {bot - top}px tall")
print(f"image content ratio if full: {W}/{bot-top}={W/(bot-top):.3f}")
