import os
import pytest
from pathlib import Path

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def _qml_path():
    here = Path(__file__).resolve().parent.parent.parent
    return here / "astromechos_imager" / "ui" / "qml" / "Step7Complete.qml"


def test_step7_complete_file_exists():
    assert _qml_path().is_file()


def test_step7_complete_contains_astromechos_branding():
    """Verify AstromechOS branding in the QML source."""
    content = _qml_path().read_text(encoding="utf-8")
    assert "AstromechOS" in content


def test_step7_complete_contains_next_steps():
    """Verify the next-steps guidance points operators at the Flask dashboard
    (the robot hotspot + the http://192.168.4.1:5000 web UI), not raw SSH."""
    content = _qml_path().read_text(encoding="utf-8")
    assert "NEXT STEPS" in content
    assert "192.168.4.1:5000" in content       # the AstromechOS dashboard URL
    # The robot's final Wi-Fi SSID is "Astromech-XXXX" (hyphen, CPU-derived
    # suffix) — NOT the bootstrap name the wizard showed earlier.
    assert "Astromech-XXXX" in content
    assert "CPU ID" in content                  # the "name will differ" caveat
    assert "dashboard" in content
    # Dashboard admin password is a live Golden default ("astro"), NOT set by
    # the Imager — must be called out so it isn't confused with the Linux/Wi-Fi
    # creds (which the Imager DOES set).
    assert '\\"astro\\"' in content


def test_step7_complete_qml_syntax(qtbot):
    """Load the QML file in an engine to check for parse errors."""
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    from astromechos_imager.ui.wizard_state import WizardState
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    from astromechos_imager.ui.theme_manager import ThemeManager

    state = WizardState()
    flash_vm = FlashViewModel(state)
    theme = ThemeManager()

    eng = QQmlApplicationEngine()
    ctx = eng.rootContext()
    ctx.setContextProperty("wizardState", state)
    ctx.setContextProperty("flashViewModel", flash_vm)
    ctx.setContextProperty("theme", theme)

    eng.load(QUrl.fromLocalFile(str(_qml_path())))
    # A root Rectangle is a valid top-level item for QQmlApplicationEngine.
    # If parse fails, rootObjects() is empty.
    assert len(eng.rootObjects()) > 0
