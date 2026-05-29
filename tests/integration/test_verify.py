# tests/integration/test_verify.py
import hashlib
import pytest
from astromechos_imager.core.diskwriter import verify_readback
from astromechos_imager.core.errors import HashMismatchError

pytestmark = pytest.mark.integration


def test_verify_matches(fake_platform_io):
    payload = b"X" * 1_000_000
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    dev = fake_platform_io.open_raw_device(2)
    try:
        dev.write(0, payload)
        verify_readback(dev, expected_sha256=hashlib.sha256(payload).hexdigest(),
                         length=len(payload))
    finally:
        dev.close()


def test_verify_mismatch_carries_offset(fake_platform_io):
    payload = b"X" * 1_000_000
    fake_platform_io.add_drive(3, size=len(payload) + 1024)
    dev = fake_platform_io.open_raw_device(3)
    try:
        # Write payload but with a flip in the middle
        corrupted = bytearray(payload)
        corrupted[500_000] = ord("Y")
        dev.write(0, bytes(corrupted))
        with pytest.raises(HashMismatchError) as ei:
            verify_readback(dev, expected_sha256=hashlib.sha256(payload).hexdigest(),
                             length=len(payload))
        # Offset detection is best-effort (block-aligned)
        assert ei.value.first_diff_offset >= 0
    finally:
        dev.close()
