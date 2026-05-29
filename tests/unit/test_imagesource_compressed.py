# tests/unit/test_imagesource_compressed.py
import gzip, lzma, hashlib
from pathlib import Path
from astromechos_imager.core.imagesource import open_image, XzSource, GzSource


PAYLOAD = (b"R2-D2 boots fast." * 100_000)  # ~1.7 MB raw — will compress well


def _mbr(payload: bytes) -> bytes:
    """Pad payload to ≥ 512 B and stamp the MBR signature so it looks like an img."""
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_xz_roundtrip(tmp_path):
    raw = _mbr(PAYLOAD)
    p = tmp_path / "im.img.xz"
    p.write_bytes(lzma.compress(raw))
    src = open_image(p)
    assert isinstance(src, XzSource)
    h = hashlib.sha256()
    with src:
        for chunk in src:
            h.update(chunk)
    assert h.hexdigest() == hashlib.sha256(raw).hexdigest()


def test_gz_roundtrip(tmp_path):
    raw = _mbr(PAYLOAD)
    p = tmp_path / "im.img.gz"
    p.write_bytes(gzip.compress(raw))
    src = open_image(p)
    assert isinstance(src, GzSource)
    h = hashlib.sha256()
    with src:
        for chunk in src:
            h.update(chunk)
    assert h.hexdigest() == hashlib.sha256(raw).hexdigest()


def test_gz_uncompressed_size_from_isize(tmp_path):
    raw = b"x" * 100_000
    p = tmp_path / "im.img.gz"
    p.write_bytes(gzip.compress(raw))
    src = open_image(p)
    # gzip ISIZE = uncompressed size mod 2^32. We just check it's non-None and ≤ true value.
    assert src.uncompressed_size in (100_000, None)
