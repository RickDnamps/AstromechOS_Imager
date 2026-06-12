import os
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


class FakeResult:
    def __init__(self, ok=True):
        self.ok = ok
        self.error = None if ok else "boom"


class FakeJob:
    """Minimal duck for FlashJob — single role, run() + on_progress + cancel_event.

    Mirrors the production sequential contract: ONE job per cycle whose
    progress routes to the channel matching its role (the pair duck died
    with PairFlashJob).
    """

    def __init__(self, should_fail=False, role_value="master"):
        from astromechos_imager.core.models import Role
        self.role = Role.MASTER if role_value == "master" else Role.SLAVE
        self.on_progress = None
        self.cancel_event = threading.Event()
        self._should_fail = should_fail

    def run(self):
        from astromechos_imager.core.diskwriter import DiskWriterProgress
        for frac in (0.25, 0.5, 0.75, 1.0):
            if self.cancel_event.is_set():
                break
            self.on_progress(DiskWriterProgress(
                phase="decompress_write", bytes_done=int(frac * 1_000_000),
                bytes_total=1_000_000, throughput_bps=0.0,
            ))
        return FakeResult(ok=not self._should_fail)


def _make_vm(qtbot):
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    from astromechos_imager.ui.wizard_state import WizardState
    state = WizardState()
    vm = FlashViewModel(state)
    return vm


def test_initial_status_is_idle(qtbot):
    vm = _make_vm(qtbot)
    assert vm.status == "idle"
    assert vm.masterProgress == 0.0


def test_start_with_fake_job_runs_to_done(qtbot):
    vm = _make_vm(qtbot)
    job = FakeJob()
    vm.startWithJob(job)
    # Wait for the QThread to finish — generous timeout
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)
    assert vm.status == "done"
    assert vm.masterProgress == 1.0


def test_start_with_failing_job_reports_error(qtbot):
    vm = _make_vm(qtbot)
    job = FakeJob(should_fail=True)
    vm.startWithJob(job)
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)
    assert vm.status == "error"
    assert "boom" in vm.errorMessage


def test_cancel_sets_job_cancel_event(qtbot):
    vm = _make_vm(qtbot)
    job = FakeJob()
    vm.startWithJob(job)
    vm.cancel()
    assert job.cancel_event.is_set()
    # Audit High #10/#14: cancel() now flips status immediately to
    # "cancelling", and _on_finished routes to "cancelled" (not "error").
    assert vm.status in ("cancelling", "cancelled")
    # Drain the worker thread before teardown.
    deadline = time.time() + 5
    while vm.status not in ("cancelled", "done", "error") and time.time() < deadline:
        qtbot.wait(50)
    assert vm.status == "cancelled"


def test_start_while_flashing_is_noop(qtbot):
    """Calling startWithJob while already flashing should be ignored."""
    vm = _make_vm(qtbot)
    job1 = FakeJob()
    job2 = FakeJob()
    vm.startWithJob(job1)
    assert vm.status == "flashing"
    # Try to start again — should be ignored
    vm.startWithJob(job2)
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)
    # Only the first job ran
    assert vm.status == "done"


def test_slave_role_routes_to_slave_channel(qtbot):
    """A slave-cycle job's progress must land on slaveProgress (the
    role-aware routing regression: a hard-wired master channel left the
    slave bar frozen at 0% over a healthy flash)."""
    vm = _make_vm(qtbot)
    job = FakeJob(role_value="slave")
    vm.startWithJob(job)
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)
    assert vm.status == "done"
    assert vm.slaveProgress == 1.0
    assert vm.slavePhase == "decompress_write"


class _RaisingJob:
    """Job whose run() raises mid-flash AND sets cancel_event before raising.

    Mirrors what DiskWriter's consumer thread does in
    ``diskwriter.py::run`` when a write fails: the consumer's
    ``except BaseException`` branch sets the shared cancel event before
    propagating the exception so the producer can unblock. Without the
    ``_user_cancelled`` flag this looks identical to a user cancel to
    ``_on_finished`` — a regression there used to silently route real
    failures to status="cancelled" (no QML rendering ⇒ UI reverts to
    idle, WRITE button reappears, operator never sees the error).
    """

    def __init__(self):
        from astromechos_imager.core.models import Role
        self.role = Role.MASTER
        self.on_progress = None
        self.cancel_event = threading.Event()

    def run(self):
        self.cancel_event.set()  # ← what DiskWriter does on consumer crash
        raise RuntimeError("simulated mid-flash WriteFile failure")


def test_write_failure_does_not_masquerade_as_cancel(qtbot):
    """Regression: real flash failure must surface as 'error', not 'cancelled'.

    The cancel event is shared between the user's cancel() path and
    DiskWriter's thread-coordination signal. Routing by event alone
    would hide every write error behind the cancelled-state idle UI.
    The fix keys the routing off an explicit ``_user_cancelled`` flag
    set ONLY by ``cancel()``.
    """
    vm = _make_vm(qtbot)
    job = _RaisingJob()
    vm.startWithJob(job)
    deadline = time.time() + 5
    while vm.status in ("flashing",) and time.time() < deadline:
        qtbot.wait(50)
    assert vm.status == "error", (
        f"expected status=error after a failing flash; got {vm.status!r}. "
        "If this is 'cancelled', _on_finished is back to keying off "
        "cancel_event.is_set() instead of _user_cancelled."
    )
    assert "WriteFile" in vm.errorMessage or "RuntimeError" in vm.errorMessage
