"""WP6 (C2) - drive selection is a PURE STATE WRITE, no hardware side effect.

Inverts the pre-WP6 contract: setMasterDriveId/setSlaveDriveId used to spawn
a release-letters daemon thread (the audit R1 race: that thread could hold a
GENERIC_WRITE volume handle while flash-time lock_and_dismount ran). Letters
are now stripped for all non-suspect candidates at drive-model bring-up
(ui/app.py); the setters must never touch the platform again.
"""
from __future__ import annotations

import threading

import pytest

pytest.importorskip("PySide6")
from astromechos_imager.ui.wizard_state import WizardState  # noqa: E402


def test_constructor_takes_no_platform_hook():
    """The release_disk_letters injection seam is gone - constructing with
    it must fail loudly, not be silently ignored."""
    with pytest.raises(TypeError):
        WizardState(release_disk_letters=lambda _id: None)


def test_setters_are_pure_state_writes():
    """Setting a drive id spawns NO thread and performs no platform call."""
    state = WizardState()
    before = {t.name for t in threading.enumerate()}
    state.setMasterDriveId(2)
    state.setSlaveDriveId(3)
    after = {t.name for t in threading.enumerate()}
    spawned = {n for n in (after - before) if n.startswith("release-letters")}
    assert spawned == set()
    assert state.masterDriveId == 2
    assert state.slaveDriveId == 3


def test_clear_to_minus_one_still_works():
    state = WizardState()
    state.setMasterDriveId(2)
    state.setMasterDriveId(-1)
    assert state.masterDriveId == -1
