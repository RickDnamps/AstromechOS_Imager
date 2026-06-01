"""Integration test for lock + dismount on a real SD card.

Skipped in normal CI — requires a physical SD card and INTEGRATION_REAL_SD env var.
To run manually: INTEGRATION_REAL_SD=E pytest tests/integration/test_lock_dismount.py -v
"""
import os
import sys
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only"),
    pytest.mark.skipif("INTEGRATION_REAL_SD" not in os.environ,
                       reason="set INTEGRATION_REAL_SD=<letter> to enable"),
]


def test_lock_and_dismount_real_sd():
    from astromechos_imager.platform.windows import lock_and_dismount
    letter = os.environ["INTEGRATION_REAL_SD"].rstrip(":")
    # Contract (baseline 67138da, restored): lock_and_dismount dismounts +
    # releases internally and returns [] — it does NOT hand back a held
    # lock. The write is authorised by the dismount + DeleteVolumeMountPointW
    # + IOCTL_DISK_DELETE_DRIVE_LAYOUT (in open_raw_device), not a held lock.
    handles = lock_and_dismount((letter,))
    assert handles == []
