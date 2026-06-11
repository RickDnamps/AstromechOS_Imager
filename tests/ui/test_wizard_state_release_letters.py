"""WizardState drive-letter release hook (bug fix 2026-06-11).

A card inserted BEFORE app launch keeps its Explorer drive letter —
automount-off at startup only blocks NEW mounts. The fix detaches the
letters the moment the operator SELECTS the card as Master/Slave, via an
injected callable so WizardState stays platform-free and these tests can
never touch a real disk.
"""
from __future__ import annotations

import time

from astromechos_imager.ui.wizard_state import WizardState


def _wait_for(predicate, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_selection_invokes_release_hook_for_both_roles():
    """Selecting a Master AND a Slave drive each fire the injected hook with
    the selected physical drive id (in a worker thread)."""
    calls: list[int] = []
    state = WizardState(release_disk_letters=calls.append)

    state.setMasterDriveId(2)
    state.setSlaveDriveId(3)

    assert _wait_for(lambda: sorted(calls) == [2, 3]), f"hook calls: {calls}"


def test_no_hook_means_no_side_effects():
    """Default construction (unit tests, non-Windows) must be a pure no-op —
    the setters still work and nothing is ever invoked."""
    state = WizardState()  # release_disk_letters=None
    state.setMasterDriveId(1)
    state.setSlaveDriveId(2)
    assert state.masterDriveId == 1
    assert state.slaveDriveId == 2


def test_negative_drive_id_never_fires_hook():
    """resetForNextCycle-style clears (id = -1) must not trigger a release."""
    calls: list[int] = []
    state = WizardState(release_disk_letters=calls.append)

    state.setMasterDriveId(2)
    assert _wait_for(lambda: calls == [2])
    state.setMasterDriveId(-1)   # cycle reset path
    time.sleep(0.05)
    assert calls == [2], f"unexpected hook call on clear: {calls}"


def test_hook_exception_never_breaks_the_setter():
    """A failing platform hook is best-effort: the wizard state still
    updates and no exception escapes to the UI."""
    def boom(_drive_id: int) -> None:
        raise OSError("FSCTL exploded")

    state = WizardState(release_disk_letters=boom)
    state.setMasterDriveId(4)        # must not raise
    assert state.masterDriveId == 4
    time.sleep(0.05)                 # let the daemon thread run the failure
