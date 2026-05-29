# tests/integration/test_diskwriter.py
import hashlib
import lzma
import pytest
from astromechos_imager.core.diskwriter import DiskWriter, DiskWriterProgress
from astromechos_imager.core.imagesource import open_image

pytestmark = pytest.mark.integration


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_writes_raw_image_to_fake_device(tmp_path, fake_platform_io):
    payload = _mbr(b"R2D2" * 250_000)
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    src_path = tmp_path / "im.img"
    src_path.write_bytes(payload)

    events: list = []
    def on_progress(p: DiskWriterProgress):
        events.append((p.phase, p.bytes_done))

    with open_image(src_path) as src:
        dev = fake_platform_io.open_raw_device(2)
        try:
            dw = DiskWriter(src, dev, on_progress=on_progress)
            result = dw.run()
        finally:
            dev.close()
    assert result.bytes_written == len(payload)
    assert result.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert any(phase == "decompress_write" for phase, _ in events)


def test_writes_xz_image_to_fake_device(tmp_path, fake_platform_io):
    payload = _mbr(b"hello" * 500_000)
    fake_platform_io.add_drive(3, size=len(payload) + 1024)
    src_path = tmp_path / "im.img.xz"
    src_path.write_bytes(lzma.compress(payload))
    with open_image(src_path) as src:
        dev = fake_platform_io.open_raw_device(3)
        try:
            dw = DiskWriter(src, dev)
            result = dw.run()
        finally:
            dev.close()
    assert result.source_sha256 == hashlib.sha256(payload).hexdigest()
