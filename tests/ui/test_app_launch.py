import os
import pytest
from pathlib import Path

# Headless Qt — the conftest at project root must not enforce offscreen, so we
# set it locally here. CI uses QT_QPA_PLATFORM=offscreen as the env var.
pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def test_build_app_returns_app_engine_and_state(qtbot):
    from astromechos_imager.ui.app import build_app
    from astromechos_imager.ui.wizard_state import WizardState
    app, engine, state = build_app()
    assert app is not None
    assert engine.rootObjects(), "main.qml failed to load"
    assert isinstance(state, WizardState)
    assert state.currentStep == 1


def test_splash_asset_path_resolves_in_dev():
    from astromechos_imager.ui.app import splash_asset_path
    p = splash_asset_path()
    assert p.is_file(), f"Expected splash asset at {p}"
    assert p.suffix == ".png"


def test_splash_asset_context_property_set(qtbot):
    """The QML engine must receive splashImageUrl before main.qml loads."""
    from PySide6.QtCore import QUrl
    from astromechos_imager.ui.app import build_app, splash_asset_path
    app, engine, state = build_app()
    val = engine.rootContext().contextProperty("splashImageUrl")
    assert isinstance(val, QUrl)
    assert val.isLocalFile()
    # The QUrl should resolve to the same file as splash_asset_path()
    assert Path(val.toLocalFile()) == splash_asset_path()


def test_window_title_is_astromechos(qtbot):
    from astromechos_imager.ui.app import build_app
    app, engine, state = build_app()
    root = engine.rootObjects()[0]
    assert root.property("title") == "AstromechOS Imager"


def test_wizard_state_context_property(qtbot):
    from astromechos_imager.ui.app import build_app
    from astromechos_imager.ui.wizard_state import WizardState
    app, engine, state = build_app()
    ctx_state = engine.rootContext().contextProperty("wizardState")
    assert isinstance(ctx_state, WizardState)
    assert ctx_state is state
