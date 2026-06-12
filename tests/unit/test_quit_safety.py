"""WP5 - quit safety: thread parking + cancel-aware poll pause (R2/F4)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QThread  # noqa: E402

from astromechos_imager.ui.flash_view_model import FlashViewModel  # noqa: E402


@pytest.fixture()
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


class _WizardStub:
    currentRole = "master"
    verifyIntegrity = False


def test_park_overrun_thread_keeps_reference(qapp):
    vm = FlashViewModel(_WizardStub())
    t = QThread()
    vm._park_overrun_thread(t, object())
    assert any(z[0] is t for z in vm._zombie_threads)


def test_park_overrun_thread_prunes_finished(qapp):
    vm = FlashViewModel(_WizardStub())
    done = QThread()
    done.start()
    done.quit()
    assert done.wait(2000)
    vm._park_overrun_thread(done, None)        # parked, already finished
    live = QThread()
    vm._park_overrun_thread(live, None)        # parking prunes the dead one
    parked = [z[0] for z in vm._zombie_threads]
    assert done not in parked
    assert live in parked


def test_cancelling_status_pauses_polling_contract():
    """Pin the pause-set the app wires in _sync_drive_polling (audit R2):
    the WMI poll must stay paused while the worker runs its cancel cleanup
    (diskpart exFAT restore against a RAW disk races the ASSOCIATORS query).
    The set lives inline in app.py's closure; this test pins the source so
    a regression is at least loud."""
    import inspect

    from astromechos_imager.ui import app as app_mod
    src = inspect.getsource(app_mod)
    assert '"cancelling"' in src.split("_sync_drive_polling", 1)[1].split(
        "stop_polling", 1)[0], (
        "_sync_drive_polling must pause the drive poll during 'cancelling'"
    )
