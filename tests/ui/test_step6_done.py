import os
import pytest
from pathlib import Path

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def _qml_path():
    here = Path(__file__).resolve().parent.parent.parent
    return here / "astromechos_imager" / "ui" / "qml" / "Step6Done.qml"


def test_step6_done_file_exists():
    assert _qml_path().is_file()


def test_step6_done_contains_astromechos_branding():
    """Verify AstromechOS branding in the QML source."""
    content = _qml_path().read_text(encoding="utf-8")
    assert "AstromechOS" in content


def test_step6_done_contains_next_steps():
    """Verify that next-steps guidance text is present."""
    content = _qml_path().read_text(encoding="utf-8")
    assert "Next steps" in content
    assert "astromech-master.local" in content
    assert "astromech-slave.local" in content


def test_step6_done_qml_syntax(qtbot):
    """Load the QML file in an engine to check for parse errors."""
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    from astromechos_imager.ui.wizard_state import WizardState
    from astromechos_imager.ui.flash_view_model import FlashViewModel

    state = WizardState()
    flash_vm = FlashViewModel(state)

    eng = QQmlApplicationEngine()
    ctx = eng.rootContext()
    ctx.setContextProperty("wizardState", state)
    ctx.setContextProperty("flashViewModel", flash_vm)

    # Step6Done uses wizardState context — provide it before loading
    eng.load(QUrl.fromLocalFile(str(_qml_path())))
    # A root Rectangle is a valid top-level item for QQmlApplicationEngine
    # If parse fails, rootObjects() is empty
    assert len(eng.rootObjects()) > 0
