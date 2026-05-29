import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def test_initial_step_is_one(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.currentStep == 1


def test_next_advances(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.next()
    assert s.currentStep == 2
    s.next()
    s.next()
    assert s.currentStep == 4


def test_back_decrements(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.next(); s.next(); s.next()  # 4
    s.back()
    assert s.currentStep == 3


def test_back_clamps_at_min(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.back()
    s.back()
    assert s.currentStep == 1


def test_next_clamps_at_max(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    for _ in range(10):
        s.next()
    assert s.currentStep == 6


def test_goto_valid_range(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.goto(5)
    assert s.currentStep == 5


def test_goto_out_of_range_noop(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.goto(0)
    s.goto(7)
    s.goto(-1)
    assert s.currentStep == 1


def test_signal_emitted_on_change(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.currentStepChanged.connect(lambda v: received.append(v))
    s.next()
    s.next()
    s.back()
    assert received == [2, 3, 2]


def test_signal_not_emitted_on_clamp(qtbot):
    """Clamped no-op transitions must NOT spam the signal."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.currentStepChanged.connect(lambda v: received.append(v))
    s.back()  # at 1, clamps — no signal
    s.back()  # still at 1
    assert received == []
