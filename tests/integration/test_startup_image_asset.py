"""Integration tests for the startup screen image asset.

Validates file existence, PNG integrity, canvas dimensions, colour mode,
and a reasonable file-size range.  No pixel-level or OCR checks — visual
inspection of the copyright overlay is deferred to human review.
"""

import pytest
from pathlib import Path
from PIL import Image

pytestmark = pytest.mark.integration

ASSET = Path("astromechos_imager/ui/resources/images/startup_screen_final.png")


def test_asset_exists():
    assert ASSET.is_file(), f"Missing startup image asset at {ASSET}"


def test_asset_is_valid_png():
    with Image.open(ASSET) as im:
        im.verify()                            # PNG integrity check


def test_asset_dimensions_acceptable():
    with Image.open(ASSET) as im:
        assert im.size == (800, 600), f"Expected 800x600, got {im.size}"


def test_asset_has_alpha_or_rgb():
    with Image.open(ASSET) as im:
        assert im.mode in ("RGBA", "RGB"), f"Unexpected mode {im.mode}"


def test_asset_size_reasonable():
    # ~50 KB lower bound (must contain actual image data) and 2 MB upper bound
    size = ASSET.stat().st_size
    assert 50_000 < size < 2_000_000, f"Suspicious asset size: {size} bytes"
