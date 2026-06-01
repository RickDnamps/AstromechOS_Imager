# tests/integration/test_diskwriter.py
import hashlib
import lzma
import time
import pytest
from astromechos_imager.core.diskwriter import (
    DiskWriter, DiskWriterProgress, verify_readback,
)
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


class _SlowDevice:
    """RawDevice whose write() sleeps, so the consumer lags the producer and
    the bounded queue is FULL when the producer finishes — reproducing a
    real (slow) SD card's timing in-memory."""
    sector_size = 512

    def __init__(self, size, per_write_s=0.01):
        self._buf = bytearray(size)
        self._slow = per_write_s

    def write(self, offset, data):
        time.sleep(self._slow)
        self._buf[offset:offset + len(data)] = data
        return len(data)

    def read(self, offset, length):
        return bytes(self._buf[offset:offset + length])

    def flush(self):
        pass

    def close(self):
        pass


def test_slow_consumer_does_not_drop_last_chunk(tmp_path):
    """Regression: on a slow target the producer's end-of-stream sentinel
    must NOT discard a queued data chunk.

    The old ``q.get_nowait()`` drop-to-fit silently dropped the last chunk
    when the queue was full at producer finish (always, on slow devices),
    leaving the device ~1 MB short, ``bytes_written`` undercounted, and
    verify_readback comparing a short readback against the full-image hash
    → a deterministic SHA-256 mismatch on every large flash. With the
    deferred first block in play, this asserts the full image length is
    written AND that verify_readback passes end-to-end.
    """
    # >> QUEUE_MAX (4) chunks of 1 MB each so the queue is genuinely full
    # at producer finish under the slow writes.
    payload = _mbr(bytes((i // (1 << 20)) & 0xFF for i in range(8 * (1 << 20) + 4096)))
    src_path = tmp_path / "big.img"
    src_path.write_bytes(payload)

    dev = _SlowDevice(len(payload) + (1 << 20), per_write_s=0.01)
    with open_image(src_path) as src:
        dw = DiskWriter(src, dev)          # defer_first_block=True (default)
        result = dw.run()

    # No chunk dropped: the full image length is accounted for.
    assert result.bytes_written == len(payload), (
        f"bytes_written {result.bytes_written} != image length {len(payload)} "
        "— a queued chunk was dropped at producer finish (regression)."
    )
    assert result.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.first_block_data is not None

    # Write the deferred first block, then verify_readback the way the
    # orchestrator does — it must MATCH (length == bytes_written covers the
    # whole image; no 1-MB shortfall).
    dev.write(0, result.first_block_data)
    verify_readback(
        dev, result.source_sha256, result.bytes_written,
        first_block=result.first_block_data,
    )  # raises HashMismatchError on regression
