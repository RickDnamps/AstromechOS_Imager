import os
from pathlib import Path
from types import SimpleNamespace

import pytest

# Headless Qt — the conftest at project root must not enforce offscreen, so we
# set it locally here. CI uses QT_QPA_PLATFORM=offscreen as the env var.
pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


class _FakePlatformIO:
    def enumerate_removable_drives(self, include_letters=True):
        return []


def _fake_win():
    """WP8 fake of the platform.windows surface build_app() consumes.

    Records every call so tests can assert the seam is actually used —
    and the conftest sentinel guarantees no real mountvol ever runs.
    """
    calls = []

    def rec(name, ret=True):
        def _f(*a, **k):
            calls.append(name)
            return ret
        return _f

    fake = SimpleNamespace(
        _suppress_shell_error_dialogs_for_process=rec("suppress", None),
        restore_automount_if_crashed=rec("restore", None),
        disable_automount=rec("disable", True),
        enable_automount=rec("enable", True),
        is_elevated=rec("elevated", True),
        letters_on_disk=rec("letters", []),
        force_unmount_letter=rec("force", True),
        WindowsPlatformIO=_FakePlatformIO,
    )
    fake.calls = calls
    return fake


def _build(qtbot):
    from astromechos_imager.ui.app import build_app
    fake = _fake_win()
    app, engine, state = build_app(platform_win=fake)
    return app, engine, state, fake


def test_build_app_returns_app_engine_and_state(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    app, engine, state, fake = _build(qtbot)
    assert app is not None
    assert engine.rootObjects(), "main.qml failed to load"
    assert isinstance(state, WizardState)
    assert state.currentStep == 1


def test_build_app_uses_injected_seam_not_real_platform(qtbot):
    """The session guard must run through the injected surface (WP8/A7).

    Arming is asynchronous since A6 (background thread) — wait for the
    worker to report through the fake before asserting.
    """
    app, engine, state, fake = _build(qtbot)
    qtbot.waitUntil(lambda: "disable" in fake.calls, timeout=3000)
    assert "restore" in fake.calls


def test_system_status_context_property(qtbot):
    """QML reads systemStatus.automountDefenseActive live (A6)."""
    from astromechos_imager.ui.system_status import SystemStatus
    app, engine, state, fake = _build(qtbot)
    status = engine.rootContext().contextProperty("systemStatus")
    assert isinstance(status, SystemStatus)
    qtbot.waitUntil(lambda: "disable" in fake.calls, timeout=3000)
    assert status.automountDefenseActive is True  # fake disable_automount -> True


def test_splash_asset_path_resolves_in_dev():
    from astromechos_imager.ui.app import splash_asset_path
    p = splash_asset_path()
    assert p.is_file(), f"Expected splash asset at {p}"
    assert p.suffix == ".png"


def test_splash_asset_context_property_set(qtbot):
    """The QML engine must receive splashImageUrl before main.qml loads."""
    from PySide6.QtCore import QUrl

    from astromechos_imager.ui.app import splash_asset_path
    app, engine, state, fake = _build(qtbot)
    val = engine.rootContext().contextProperty("splashImageUrl")
    assert isinstance(val, QUrl)
    assert val.isLocalFile()
    # The QUrl should resolve to the same file as splash_asset_path()
    assert Path(val.toLocalFile()) == splash_asset_path()


def test_window_title_is_astromechos(qtbot):
    app, engine, state, fake = _build(qtbot)
    root = engine.rootObjects()[0]
    assert root.property("title") == "AstromechOS Imager"


def test_wizard_state_context_property(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    app, engine, state, fake = _build(qtbot)
    ctx_state = engine.rootContext().contextProperty("wizardState")
    assert isinstance(ctx_state, WizardState)
    assert ctx_state is state
