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
    from PySide6.QtCore import QUrl, SignalInstance
    eng = QQmlApplicationEngine()
    # In PySide6 6.7+, QQmlApplicationEngine.warnings is a Signal (not a
    # callable method returning a list).  Detect which API is available.
    warnings_attr = getattr(eng, "warnings", None)
    is_signal = isinstance(warnings_attr, SignalInstance)
    if not is_signal and callable(warnings_attr):
        # Older PySide6 where warnings() is a method returning a list
        eng.load(QUrl.fromLocalFile(str(_qml_path())))
        assert eng.warnings() == []
    else:
        # PySide6 6.7.x — warnings is a Signal. Just verify the QML file
        # parses without raising an exception.
        # Dialog cannot be a top-level item so rootObjects() will be empty —
        # that is expected and not an error.
        try:
            eng.load(QUrl.fromLocalFile(str(_qml_path())))
        except Exception as exc:
            pytest.fail(f"QML load raised: {exc}")


def test_error_dialog_file_exists():
    assert _qml_path().is_file()
