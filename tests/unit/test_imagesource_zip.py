# tests/unit/test_imagesource_zip.py
import hashlib
import zipfile

import pytest

from astromechos_imager.core.errors import ImageFormatError
from astromechos_imager.core.imagesource import ZipSource, open_image


def _mbr(payload: bytes) -> bytes:
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_zip_with_single_img(tmp_path):
    raw = _mbr(b"hello" * 200_000)
    z = tmp_path / "im.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("master.img", raw)
    src = open_image(z)
    assert isinstance(src, ZipSource)
    assert src.uncompressed_size == len(raw)
    h = hashlib.sha256()
    with src:
        for c in src:
            h.update(c)
    assert h.hexdigest() == hashlib.sha256(raw).hexdigest()


def test_zip_with_zero_img_rejected(tmp_path):
    z = tmp_path / "empty.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", b"hi")
    with pytest.raises(ImageFormatError):
        open_image(z)


def test_zip_with_multiple_img_rejected(tmp_path):
    raw = _mbr(b"x" * 100_000)
    z = tmp_path / "multi.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.img", raw)
        zf.writestr("b.img", raw)
    with pytest.raises(ImageFormatError):
        open_image(z)
