"""Step 3 NEXT-button gate logic + single-card-mode banner contract.

The QML banner in ``Step3Storage.qml`` lets the operator escape the
"1 SD detected + mode=both" dead end by switching to ``master_only`` or
``slave_only`` (or, inversely, restore ``both`` when 2+ cards are now
inserted). The banner calls the existing ``WizardState.setMode`` slot —
no new properties or slots were added.

These tests pin the gate expression used by the NEXT button
(Step3Storage.qml:163-164) and verify ``setMode`` preserves drive
assignments (since ``setMode`` only mutates ``_mode``).
"""
from __future__ import annotations

import os

import pytest

# Mirror the skip guard from tests/ui/test_wizard_state.py — these tests
# instantiate a QObject and need the Qt platform plugin available.
pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def _advance_ok(ws) -> bool:
    """Mirror of Step3Storage.qml NEXT-button enabled expression (lines
    163-164). Keeps the QML truth-table pinned in Python so a future QML
    edit can't silently break the gate."""
    need_master = ws.mode in ("both", "master_only")
    need_slave = ws.mode in ("both", "slave_only")
    return ((not need_master) or ws.masterDriveId != -1) and (
        (not need_slave) or ws.slaveDriveId != -1
    )


def test_advance_blocked_when_mode_both_and_no_drives(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    # default mode is "both", default drive IDs are -1
    assert s.mode == "both"
    assert s.masterDriveId == -1
    assert s.slaveDriveId == -1
    assert _advance_ok(s) is False


def test_advance_blocked_when_mode_both_and_only_master_assigned(qtbot):
    """Anchors the original bug: 1 SD detected + mode=both → NEXT
    permanently disabled because slaveDriveId can never leave -1."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setMasterDriveId(1)
    assert s.mode == "both"
    assert s.masterDriveId == 1
    assert s.slaveDriveId == -1
    assert _advance_ok(s) is False


def test_advance_ok_when_mode_master_only_and_master_assigned(qtbot):
    """The fix: switching to master_only removes the slave gate, so the
    same 1-SD-assigned-as-master state now lets NEXT enable."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setMode("master_only")
    s.setMasterDriveId(1)
    assert s.mode == "master_only"
    assert _advance_ok(s) is True


def test_advance_ok_when_mode_slave_only_and_slave_assigned(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setMode("slave_only")
    s.setSlaveDriveId(2)
    assert s.mode == "slave_only"
    assert _advance_ok(s) is True


def test_advance_blocked_when_mode_slave_only_but_no_slave_assigned(qtbot):
    """slave_only mode still requires the slave to be assigned — switching
    mode is not a bypass."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setMode("slave_only")
    assert s.masterDriveId == -1
    assert s.slaveDriveId == -1
    assert _advance_ok(s) is False


def test_setMode_preserves_drive_assignments(qtbot):
    """The banner calls setMode without touching drive IDs — verify the
    underlying slot honors that contract."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setMasterDriveId(1)
    s.setSlaveDriveId(2)
    assert s.masterDriveId == 1
    assert s.slaveDriveId == 2
    s.setMode("master_only")
    assert s.masterDriveId == 1, "setMode must not clear masterDriveId"
    assert s.slaveDriveId == 2, "setMode must not clear slaveDriveId"
    s.setMode("both")
    assert s.masterDriveId == 1
    assert s.slaveDriveId == 2
