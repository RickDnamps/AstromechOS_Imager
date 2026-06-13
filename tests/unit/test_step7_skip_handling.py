"""Step 7 Complete — partial vs full deployment recap.

The Step 7 QML screen builds its "next steps" list and its headline
text from ``wizardState.completedRoles``. Pure-Python tests can't
render QML, so instead we lock the *inputs* the QML reads:

  * ``completedRoles == ["master"]`` → ``proposedNextRole == "slave"``
    (mirrors the "re-run the Imager to flash the SLAVE card" branch)
  * ``completedRoles == ["slave"]``  → ``proposedNextRole == "master"``
  * both done                       → ``proposedNextRole == ""``
    (mirrors the "DEPLOYMENT COMPLETE" branch)

These properties drive the Step7Complete ``nextStepsModel`` and
``bothDone`` derivations end-to-end.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable Step 7 recap tests",
)


def test_partial_completion_master_done_proposes_slave():
    """Only MASTER flashed → Step 7 must steer the operator to flash
    SLAVE on the next run (partial-deployment branch)."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.markCurrentRoleCompleted()
    assert list(s.completedRoles) == ["master"]
    assert s.proposedNextRole == "slave"


def test_partial_completion_slave_done_proposes_master():
    """Only SLAVE flashed → Step 7 must steer toward MASTER next."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("slave")
    s.markCurrentRoleCompleted()
    assert list(s.completedRoles) == ["slave"]
    assert s.proposedNextRole == "master"


def test_full_completion_via_two_marks():
    """Both roles flashed → Step 7 headline switches to DEPLOYMENT
    COMPLETE and the next-steps list reverts to the dual-card
    instructions."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.markCurrentRoleCompleted()
    s.resetForNextCycle()
    s.setCurrentRole("slave")
    s.markCurrentRoleCompleted()
    assert set(s.completedRoles) == {"master", "slave"}
    assert s.proposedNextRole == ""


def test_partial_then_full_proposal_transitions():
    """The transition from partial → full must collapse the proposed
    role to "" so the Step 7 headline flips to DEPLOYMENT COMPLETE."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setCurrentRole("master")
    s.markCurrentRoleCompleted()
    assert s.proposedNextRole == "slave"
    s.resetForNextCycle()
    s.setCurrentRole("slave")
    s.markCurrentRoleCompleted()
    assert s.proposedNextRole == ""
