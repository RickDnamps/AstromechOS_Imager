"""Smoke tests for Step1Mode.qml — card-style mode picker."""
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def test_step1_mode_qml_exists():
    """Step1Mode.qml must exist in the qml directory."""
    from pathlib import Path
    qml = Path(__file__).resolve().parents[2] / "astromechos_imager" / "ui" / "qml" / "Step1Mode.qml"
    assert qml.is_file(), f"Step1Mode.qml not found at {qml}"


def test_step1_mode_qml_contains_mode_choices():
    """Step1Mode.qml must reference all three mode values."""
    from pathlib import Path
    qml = Path(__file__).resolve().parents[2] / "astromechos_imager" / "ui" / "qml" / "Step1Mode.qml"
    content = qml.read_text(encoding="utf-8")
    assert '"both"' in content
    assert '"master_only"' in content
    assert '"slave_only"' in content


def test_step1_mode_qml_references_wizard_state():
    """Step1Mode.qml must reference wizardState.mode and wizardState.setMode."""
    from pathlib import Path
    qml = Path(__file__).resolve().parents[2] / "astromechos_imager" / "ui" / "qml" / "Step1Mode.qml"
    content = qml.read_text(encoding="utf-8")
    assert "wizardState.mode" in content
    assert "wizardState.setMode" in content
    assert "wizardState.next()" in content


def test_wizard_state_valid_modes():
    """WizardState must expose VALID_MODES tuple with the three values."""
    from astromechos_imager.ui.wizard_state import WizardState
    assert WizardState.MODE_BOTH == "both"
    assert WizardState.MODE_MASTER_ONLY == "master_only"
    assert WizardState.MODE_SLAVE_ONLY == "slave_only"
    assert set(WizardState.VALID_MODES) == {"both", "master_only", "slave_only"}


def test_set_mode_slave_only(qtbot):
    """Confirm slave_only mode is accepted."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setMode("slave_only")
    assert s.mode == "slave_only"
