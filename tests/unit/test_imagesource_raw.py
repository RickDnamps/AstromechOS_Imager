# tests/unit/test_imagesource_raw.py
import hashlib

import pytest

from astromechos_imager.core.errors import ImageFormatError
from astromechos_imager.core.imagesource import RawSource, open_image


def test_raw_detection(tmp_path):
    p = tmp_path / "blob.img"
    payload = b"\x00" * 1024 + b"\x55\xAA"  # MBR signature near end
    p.write_bytes(payload)
    src = open_image(p)
    assert isinstance(src, RawSource)
    assert src.uncompressed_size == len(payload)


def test_raw_iteration_yields_full_content(tmp_path):
    p = tmp_path / "blob.img"
    payload = b"X" * (3 * 1024 * 1024 + 17)   # 3 MB + tail
    p.write_bytes(payload)
    with open_image(p) as src:
        chunks = list(src)
    assert b"".join(chunks) == payload
    assert all(len(c) <= src.CHUNK_SIZE for c in chunks)


def test_raw_sha256(tmp_path):
    p = tmp_path / "blob.img"
    payload = b"Y" * 1_500_000
    p.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    h = hashlib.sha256()
    with open_image(p) as src:
        for chunk in src:
            h.update(chunk)
    assert h.hexdigest() == expected


def test_unsupported_format(tmp_path):
    p = tmp_path / "weird.bin"
    p.write_bytes(b"\x01" * 100)   # too small, no MBR
    with pytest.raises(ImageFormatError):
        open_image(p)
