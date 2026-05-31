"""Sequential Deployment Assistant — wizard_state machine tests.

Locks in the cycleIndex / completedRoles / currentRole / proposedNextRole
contract added when the MODE picker was deleted. Each cycle picks ONE
role; the flash-done path calls ``markCurrentRoleCompleted`` which bumps
``cycleIndex`` and appends to ``completedRoles``. ``proposedNextRole``
derives the remaining role for Screen 4 pre-selection.

Test guard: replicates the offscreen-Qt pytestmark from
``tests/ui/test_wizard_state_step3_advance.py`` (now deleted) — the
WizardState QObject needs a Qt platform plugin to instantiate.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable sequential state tests",
)


# ── Initial state ────────────────────────────────────────────────────


def test_initial_cycle_index_is_zero():
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.cycleIndex == 0
    assert s.currentRole == ""
    assert list(s.completedRoles) == []
    assert s.proposedNextRole == ""


def test_max_step_is_seven():
    """7-step sequential wizard: Landing / Config / Images / Role / Ops /
    Cycle / Complete."""
    from astromechos_imager.ui.wizard_state import WizardState
    assert WizardState.MAX_STEP == 7


# ── setCurrentRole ───────────────────────────────────────────────────


def test_setCurrentRole_emits_signal():
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received: list[str] = []
    s.currentRoleChanged.connect(lambda v: received.append(v))
    s.setCurrentRole("master")
    assert s.currentRole == "master"
    assert received == ["master"]


def test_setCurrentRole_rejects_invalid():
    """An invalid role must be silently ignored — currentRole stays put."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.setCurrentRole("badrole")
    assert s.currentRole == "master"


def test_setCurrentRole_same_value_no_signal():
    """Idempotent — re-setting the same role does not spam the signal."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    received: list[str] = []
    s.currentRoleChanged.connect(lambda v: received.append(v))
    s.setCurrentRole("master")
    assert received == []


# ── markCurrentRoleCompleted ─────────────────────────────────────────


def test_markCurrentRoleCompleted_advances_cycle():
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.markCurrentRoleCompleted()
    assert s.cycleIndex == 1
    assert list(s.completedRoles) == ["master"]
    assert s.proposedNextRole == "slave"


def test_markCurrentRoleCompleted_idempotent():
    """Calling twice for the same role must not duplicate the entry or
    double-bump the cycle counter. This guards against the flash-done
    signal being delivered twice (Qt queued-connection edge cases)."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.markCurrentRoleCompleted()
    s.markCurrentRoleCompleted()
    assert s.cycleIndex == 1
    assert list(s.completedRoles) == ["master"]


def test_markCurrentRoleCompleted_emits_signals():
    """cycleIndexChanged and completedRolesChanged both fire on success."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    cycle_received: list[int] = []
    completed_received: list[int] = []
    s.cycleIndexChanged.connect(lambda v: cycle_received.append(v))
    s.completedRolesChanged.connect(lambda: completed_received.append(1))
    s.markCurrentRoleCompleted()
    assert cycle_received == [1]
    assert completed_received == [1]


def test_markCurrentRoleCompleted_noop_when_no_current_role():
    """Defensive: clean slate + no current role = no-op, no crash."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.markCurrentRoleCompleted()
    assert s.cycleIndex == 0
    assert list(s.completedRoles) == []


# ── proposedNextRole ─────────────────────────────────────────────────


def test_proposedNextRole_after_master_done_is_slave():
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.markCurrentRoleCompleted()
    assert s.proposedNextRole == "slave"


def test_proposedNextRole_after_slave_done_is_master():
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("slave")
    s.markCurrentRoleCompleted()
    assert s.proposedNextRole == "master"


def test_proposedNextRole_after_both_done():
    """master then slave → both done → no proposal (empty string),
    cycleIndex == 2."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.markCurrentRoleCompleted()
    s.resetForNextCycle()
    s.setCurrentRole("slave")
    s.markCurrentRoleCompleted()
    assert s.cycleIndex == 2
    assert set(s.completedRoles) == {"master", "slave"}
    assert s.proposedNextRole == ""


# ── resetForNextCycle ────────────────────────────────────────────────


def test_resetForNextCycle_clears_drive_ids_keeps_completed():
    """Per-cycle drive ids + currentRole reset, but completedRoles and
    cycleIndex persist so proposedNextRole keeps driving Screen 4."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.setMasterDriveId(2)
    s.setSlaveDriveId(3)
    s.markCurrentRoleCompleted()
    assert s.cycleIndex == 1
    assert list(s.completedRoles) == ["master"]

    s.resetForNextCycle()
    assert s.currentRole == ""
    assert s.masterDriveId == -1
    assert s.slaveDriveId == -1
    # Preserved across the cycle boundary:
    assert s.cycleIndex == 1
    assert list(s.completedRoles) == ["master"]
    assert s.proposedNextRole == "slave"


def test_resetForNextCycle_emits_signals():
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.setMasterDriveId(2)
    s.setSlaveDriveId(3)

    role_received: list[str] = []
    master_drive_received: list[int] = []
    slave_drive_received: list[int] = []
    s.currentRoleChanged.connect(lambda v: role_received.append(v))
    s.masterDriveIdChanged.connect(lambda v: master_drive_received.append(v))
    s.slaveDriveIdChanged.connect(lambda v: slave_drive_received.append(v))

    s.resetForNextCycle()
    assert role_received == [""]
    assert master_drive_received == [-1]
    assert slave_drive_received == [-1]
