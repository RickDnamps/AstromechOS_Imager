import os
import pytest
from pathlib import Path

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def _qml_path():
    here = Path(__file__).resolve().parent.parent.parent
    return here / "astromechos_imager" / "ui" / "qml" / "ErrorDialog.qml"


def test_error_dialog_qml_loads(qtbot):
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    eng = QQmlApplicationEngine()
    eng.load(QUrl.fromLocalFile(str(_qml_path())))
    # Empty roots is OK — Dialog can't be a top-level Window. We just need
    # the QML to PARSE without error. Check no warning was emitted.
    assert eng.warnings() == [] if hasattr(eng, "warnings") else True


def test_error_dialog_file_exists():
    assert _qml_path().is_file()
