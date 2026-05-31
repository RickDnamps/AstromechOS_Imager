r"""Tests for the customize-step safety block.

Verifies ``FlashJob._assert_bp_targets_our_drive`` correctly:
- accepts a ``DriveLetterBootPartition`` whose letter maps to the target
- aborts with ``CustomizeTargetMismatchError`` when the letter maps to
  a non-target removable drive (or the system drive)
- skips the check entirely for non-``DriveLetterBootPartition`` impls
  (β path writes through the raw device handle by construction)

These tests guard against a regression of the E2E audit's Bug #1 where
the orchestrator silently wrote the AstromechOS bundle to ``C:\`` because
the α fallback ``wait_for_new_drive_letter`` returned the
alphabetically-first present letter when ``known_letters_before=set()``.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from astromechos_imager.core.errors import CustomizeTargetMismatchError
from astromechos_imager.core.models import DiskRef, FirstbootConfig, Role
from astromechos_imager.core.orchestrator import FlashJob


def _job_with_target(phys_id: int, letters: tuple[str, ...], pio) -> FlashJob:
    """Build a minimal FlashJob just for the safety check."""
    target = DiskRef(
        physical_drive_id=phys_id,
        device_path=f"\\\\.\\PHYSICALDRIVE{phys_id}",
        drive_letters=letters,
        size_bytes=32 << 30,
        model="Test SD",
        serial="TEST-1",
    )
    cfg = FirstbootConfig(
        authorized_keys=[],
        imager_version="0.1.0",
        flashed_at_iso="2026-05-31T00:00:00Z",
    )
    return FlashJob(
        platform_io=pio,
        image_path=Path("/dev/null"),
        target=target,
        role=Role.MASTER,
        firstboot_config=cfg,
        master_pair=MagicMock(),
    )


def _fake_pio_returning(*disks: DiskRef):
    """Minimal PlatformIO stub whose enumerate_removable_drives returns *disks*."""
    pio = MagicMock()
    pio.enumerate_removable_drives.return_value = list(disks)
    return pio


def _fake_bp(letter: str):
    """A duck-typed DriveLetterBootPartition with the given root letter."""
    from astromechos_imager.core.bootpartition import DriveLetterBootPartition
    bp = MagicMock(spec=DriveLetterBootPartition)
    bp._root = Path(f"{letter}:\\")
    return bp


def test_safety_block_accepts_matching_letter():
    target = DiskRef(
        physical_drive_id=7, device_path="\\\\.\\PHYSICALDRIVE7",
        drive_letters=("I",), size_bytes=58 << 30,
        model="USB SD", serial="X",
    )
    pio = _fake_pio_returning(target)
    job = _job_with_target(7, ("I",), pio)
    bp = _fake_bp("I")
    # Must NOT raise — bp's letter (I) maps to target's phys_id (7)
    job._assert_bp_targets_our_drive(bp)


def test_safety_block_rejects_system_drive_letter():
    """Bug #1 regression: orchestrator must REFUSE if bp resolved to C:."""
    target = DiskRef(
        physical_drive_id=7, device_path="\\\\.\\PHYSICALDRIVE7",
        drive_letters=("I",), size_bytes=58 << 30,
        model="USB SD", serial="X",
    )
    pio = _fake_pio_returning(target)  # only the target SD is removable
    job = _job_with_target(7, ("I",), pio)
    bp = _fake_bp("C")  # ← caller mistakenly opened C:\

    with pytest.raises(CustomizeTargetMismatchError) as excinfo:
        job._assert_bp_targets_our_drive(bp)
    msg = str(excinfo.value)
    assert "SAFETY BLOCK" in msg
    assert "C" in msg
    assert "7" in msg  # phys_id
    # SD state is BOOTABLE_NO_FIRSTBOOT — operator can safely re-flash
    assert excinfo.value.sd_state == "BOOTABLE_NO_FIRSTBOOT"


def test_safety_block_rejects_other_removable_drive():
    """Two removable SDs plugged in; bp must land on the target, not the other."""
    target = DiskRef(
        physical_drive_id=7, device_path="\\\\.\\PHYSICALDRIVE7",
        drive_letters=("I",), size_bytes=58 << 30,
        model="USB SD A", serial="A",
    )
    other_sd = DiskRef(
        physical_drive_id=8, device_path="\\\\.\\PHYSICALDRIVE8",
        drive_letters=("K",), size_bytes=32 << 30,
        model="USB SD B", serial="B",
    )
    pio = _fake_pio_returning(target, other_sd)
    job = _job_with_target(7, ("I",), pio)
    bp = _fake_bp("K")  # ← would write to the OTHER plugged-in SD

    with pytest.raises(CustomizeTargetMismatchError) as excinfo:
        job._assert_bp_targets_our_drive(bp)
    assert "K" in str(excinfo.value)
    assert "7" in str(excinfo.value)


def test_safety_block_aborts_when_target_disappeared_mid_flash():
    """SD was unplugged after lock+write but before customize — must refuse."""
    pio = _fake_pio_returning()  # no removable drives at all anymore
    job = _job_with_target(7, ("I",), pio)
    bp = _fake_bp("I")

    with pytest.raises(CustomizeTargetMismatchError) as excinfo:
        job._assert_bp_targets_our_drive(bp)
    msg = str(excinfo.value)
    assert "I" in msg
    assert "(none — drive disconnected?)" in msg


def test_safety_block_aborts_when_enumerate_raises():
    pio = MagicMock()
    pio.enumerate_removable_drives.side_effect = RuntimeError("WMI down")
    job = _job_with_target(7, ("I",), pio)
    bp = _fake_bp("I")

    with pytest.raises(CustomizeTargetMismatchError) as excinfo:
        job._assert_bp_targets_our_drive(bp)
    assert "cannot re-enumerate" in str(excinfo.value)


def test_safety_block_is_noop_for_pyfatfs_path():
    """β path (PyFatFsBootPartition) writes through raw device — no letter check."""
    pio = MagicMock()
    pio.enumerate_removable_drives = MagicMock()  # ← should NEVER be called
    job = _job_with_target(7, ("I",), pio)

    class _FakePyFatBp:
        """Anything that isn't a DriveLetterBootPartition."""
        pass

    job._assert_bp_targets_our_drive(_FakePyFatBp())
    # The check must short-circuit — enumerate_removable_drives was not invoked
    pio.enumerate_removable_drives.assert_not_called()
