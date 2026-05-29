import os
import pytest
import threading
import time

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


class FakePairResult:
    def __init__(self, master_ok=True, slave_ok=True):
        class _R:
            def __init__(self, ok):
                self.ok = ok
                self.error = None if ok else "boom"
        self.master = _R(master_ok)
        self.slave = _R(slave_ok)


class FakePairJob:
    """Minimal duck for PairFlashJob — has master_target attribute and run()."""
    def __init__(self, should_fail=False):
        self.master_target = "fake-m"
        self.slave_target = "fake-s"
        self.on_progress = None
        self.cancel_event = threading.Event()
        self._should_fail = should_fail

    def run(self):
        from astromechos_imager.core.models import Role
        from astromechos_imager.core.diskwriter import DiskWriterProgress
        for frac in (0.25, 0.5, 0.75, 1.0):
            if self.cancel_event.is_set():
                break
            self.on_progress(Role.MASTER, DiskWriterProgress(
                phase="decompress_write", bytes_done=int(frac * 1_000_000),
                bytes_total=1_000_000, throughput_bps=0.0,
            ))
            self.on_progress(Role.SLAVE, DiskWriterProgress(
                phase="decompress_write", bytes_done=int(frac * 1_000_000),
                bytes_total=1_000_000, throughput_bps=0.0,
            ))
        return FakePairResult(master_ok=not self._should_fail, slave_ok=not self._should_fail)


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
    job = FakePairJob()
    vm.startWithJob(job)
    # Wait for the QThread to finish — generous timeout
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)
    assert vm.status == "done"
    assert vm.masterProgress == 1.0
    assert vm.slaveProgress == 1.0


def test_start_with_failing_job_reports_error(qtbot):
    vm = _make_vm(qtbot)
    job = FakePairJob(should_fail=True)
    vm.startWithJob(job)
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)
    assert vm.status == "error"
    assert "boom" in vm.errorMessage


def test_cancel_sets_job_cancel_event(qtbot):
    vm = _make_vm(qtbot)
    job = FakePairJob()
    vm.startWithJob(job)
    vm.cancel()
    assert job.cancel_event.is_set()
    # Wait for the thread to finish to avoid crashes during teardown
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)


def test_start_while_flashing_is_noop(qtbot):
    """Calling startWithJob while already flashing should be ignored."""
    vm = _make_vm(qtbot)
    job1 = FakePairJob()
    job2 = FakePairJob()
    vm.startWithJob(job1)
    assert vm.status == "flashing"
    # Try to start again — should be ignored
    vm.startWithJob(job2)
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)
    # Only the first job ran
    assert vm.status == "done"


def test_slave_progress_updated(qtbot):
    """Verify slave progress signals are correctly connected."""
    vm = _make_vm(qtbot)
    job = FakePairJob()
    vm.startWithJob(job)
    deadline = time.time() + 5
    while vm.status == "flashing" and time.time() < deadline:
        qtbot.wait(50)
    assert vm.slaveProgress == 1.0
    assert vm.slavePhase == "decompress_write"
