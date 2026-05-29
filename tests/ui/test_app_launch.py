import os
import pytest
from pathlib import Path

# Headless Qt — the conftest at project root must not enforce offscreen, so we
# set it locally here. CI uses QT_QPA_PLATFORM=offscreen as the env var.
pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def test_build_app_returns_app_and_engine(qtbot):
    from astromechos_imager.ui.app import build_app
    app, engine = build_app()
    assert app is not None
    assert engine.rootObjects(), "main.qml failed to load"


def test_splash_asset_path_resolves_in_dev():
    from astromechos_imager.ui.app import splash_asset_path
    p = splash_asset_path()
    assert p.is_file(), f"Expected splash asset at {p}"
    assert p.suffix == ".png"


def test_splash_asset_context_property_set(qtbot):
    """The QML engine must receive splashImageUrl before main.qml loads."""
    from PySide6.QtCore import QUrl
    from astromechos_imager.ui.app import build_app, splash_asset_path
    app, engine = build_app()
    val = engine.rootContext().contextProperty("splashImageUrl")
    assert isinstance(val, QUrl)
    assert val.isLocalFile()
    # The QUrl should resolve to the same file as splash_asset_path()
    assert Path(val.toLocalFile()) == splash_asset_path()


def test_window_title_is_astromechos(qtbot):
    from astromechos_imager.ui.app import build_app
    app, engine = build_app()
    root = engine.rootObjects()[0]
    assert root.property("title") == "AstromechOS Imager"
