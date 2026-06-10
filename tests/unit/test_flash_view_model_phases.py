"""Phase-emission contract tests for ``_FlashWorker.run()``.

These tests pin the "preparing" phase ping that the worker fires at
thread entry, BEFORE ``job.run()`` blocks on the synchronous Win32 calls
``lock_and_dismount`` / ``open_raw_device`` / ``open_image``.

Without that ping, Step5Flash.qml sits at ``status="flashing"`` +
progress 0 + empty phase label for the entire silent 1-3 s window
between SHA-256 hash done and the first ``DiskWriter`` write-byte
chunk — indistinguishable from a frozen process. The QML layer reacts
to ``phase === "preparing"`` by rendering an indeterminate stripe and
the "Preparing target drive…" label.

These tests guard against:
    - regression that defers the emit until after ``job.run()`` returns
    - regression that emits ``preparing`` only on one channel of a pair
    - regression that drops the determinate ``decompress_write`` follow-up
"""
from __future__ import annotations

import os
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


# ─── Stub jobs ────────────────────────────────────────────────────────


class _FakePairResult:
    def __init__(self, master_ok: bool = True, slave_ok: bool = True) -> None:
        class _R:
            def __init__(self, ok: bool) -> None:
                self.ok = ok
                self.error = None if ok else "boom"
        self.master = _R(master_ok)
        self.slave = _R(slave_ok)


class _FakeSingleResult:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.error = None if ok else "boom"


class _BlockingPairJob:
    """Pair job whose ``run()`` blocks until ``release_event`` is set.

    Lets the test observe that the worker emits ``preparing`` on BOTH
    channels BEFORE ``run()`` does any work — i.e. the emit happens at
    thread entry, not as a side-effect of ``on_progress`` callbacks.
    """

    def __init__(self, release_event: threading.Event) -> None:
        # ``master_target`` is the duck-type marker used by
        # ``FlashViewModel.startWithJob`` to decide pair vs single.
        self.master_target = "fake-m"
        self.slave_target = "fake-s"
        self.on_progress = None
        self.cancel_event = threading.Event()
        self._release = release_event

    def run(self):
        # Block until the test gives the all-clear.
        self._release.wait(timeout=5.0)
        return _FakePairResult()


class _BlockingSingleJob:
    """Single-target job (no ``master_target`` attribute)."""

    def __init__(self, release_event: threading.Event) -> None:
        self.on_progress = None
        self.cancel_event = threading.Event()
        self._release = release_event

    def run(self):
        self._release.wait(timeout=5.0)
        return _FakeSingleResult()


class _OneChunkPairJob:
    """Pair job that fires exactly one ``decompress_write`` chunk on the
    master channel, lets the worker drain, then returns success.

    Used to lock the sequence: ``preparing`` arrives FIRST, the real
    write phase arrives SECOND. The 0.0 / 0.1 progress fractions are
    distinct enough that order can be asserted from the captured log.
    """

    def __init__(self) -> None:
        self.master_target = "fake-m"
        self.slave_target = "fake-s"
        self.on_progress = None
        self.cancel_event = threading.Event()

    def run(self):
        from astromechos_imager.core.diskwriter import DiskWriterProgress
        from astromechos_imager.core.models import Role
        # Give the QThread event loop a chance to deliver the "preparing"
        # emits to the main-thread connections before we fire the next
        # phase — otherwise both emits race and the order assertion is
        # flaky.
        time.sleep(0.05)
        self.on_progress(
            Role.MASTER,
            DiskWriterProgress(
                phase="decompress_write",
                bytes_done=100,
                bytes_total=1000,
                throughput_bps=0.0,
            ),
        )
        return _FakePairResult()


# ─── Helpers ──────────────────────────────────────────────────────────


def _make_vm():
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    from astromechos_imager.ui.wizard_state import WizardState
    return FlashViewModel(WizardState())


def _start_worker_and_collect(job, is_pair: bool, qtbot, settle_ms: int = 200):
    """Drive ``_FlashWorker`` directly so we can observe signal order
    without going through ``FlashViewModel.startWithJob`` (which routes
    through slots that overwrite the phase string).

    Returns ``(master_events, slave_events, thread, worker)``. Caller
    is responsible for releasing any blocking event and quitting the
    thread before the test ends.
    """
    from PySide6.QtCore import QThread
    from astromechos_imager.ui.flash_view_model import _FlashWorker

    # 3-tuple (fraction, phase, throughput_bps) since the throughput
    # indicator landed end-to-end (DiskWriter → FlashViewModel → QML).
    # ``preparing`` and the deferred-first-block emit always carry
    # throughput_bps == 0.0; real write chunks carry a smoothed
    # bytes/sec sample.
    master_events: list[tuple[float, str, float]] = []
    slave_events: list[tuple[float, str, float]] = []

    thread = QThread()
    worker = _FlashWorker(job, is_pair)
    worker.moveToThread(thread)
    worker.progressMaster.connect(
        lambda f, p, t: master_events.append((f, p, t))
    )
    worker.progressSlave.connect(
        lambda f, p, t: slave_events.append((f, p, t))
    )
    thread.started.connect(worker.run)
    thread.start()

    # Let the worker's @Slot() run() entry execute and queue its first
    # emits back to the main thread's event loop.
    qtbot.wait(settle_ms)

    return master_events, slave_events, thread, worker


# ─── Tests ────────────────────────────────────────────────────────────


def test_flash_worker_emits_preparing_phase_immediately_pair(qtbot):
    """Pair flow: BOTH ``progressMaster`` and ``progressSlave`` must
    receive a ``(0.0, "preparing")`` ping BEFORE ``job.run()`` returns.
    """
    release = threading.Event()
    job = _BlockingPairJob(release)

    master_events, slave_events, thread, _w = _start_worker_and_collect(
        job, is_pair=True, qtbot=qtbot
    )

    # job.run() is still blocked, yet we must already have a preparing
    # ping on both channels. throughput must be 0.0 — no real bytes
    # have flowed through DiskWriter yet at preparing-phase entry.
    assert any(
        p == "preparing" and f == 0.0 and t == 0.0 for f, p, t in master_events
    ), (
        f"expected (0.0, 'preparing', 0.0) in master events before "
        f"job.run() returned; got {master_events!r}"
    )
    assert any(
        p == "preparing" and f == 0.0 and t == 0.0 for f, p, t in slave_events
    ), (
        f"expected (0.0, 'preparing', 0.0) in slave events before "
        f"job.run() returned; got {slave_events!r}"
    )

    # Cleanup — let the job finish so the thread quits.
    release.set()
    thread.quit()
    thread.wait(2000)


def test_flash_worker_emits_preparing_phase_immediately_single(qtbot):
    """Single (master-only) flow: ``progressMaster`` must receive
    ``(0.0, "preparing")`` before ``job.run()`` returns; ``progressSlave``
    must remain silent (no slave half-job in flight)."""
    release = threading.Event()
    job = _BlockingSingleJob(release)

    master_events, slave_events, thread, _w = _start_worker_and_collect(
        job, is_pair=False, qtbot=qtbot
    )

    assert any(
        p == "preparing" and f == 0.0 and t == 0.0 for f, p, t in master_events
    ), (
        f"expected (0.0, 'preparing', 0.0) in master events before "
        f"job.run() returned; got {master_events!r}"
    )
    assert slave_events == [], (
        f"single-target flow must NOT emit on the slave channel; "
        f"got {slave_events!r}"
    )

    release.set()
    thread.quit()
    thread.wait(2000)


class _OneChunkSingleSlaveJob:
    """Single-target job whose ``role`` is SLAVE (sequential slave cycle).

    Fires one ``decompress_write`` chunk through the single-job on_progress
    callback. Used to lock the regression fix: a single SLAVE job must report
    on the SLAVE channel, not the master channel — otherwise the slave-cycle
    progress bar (which reads slaveProgress) sits frozen at 0% over a healthy
    write and the operator cancels it.
    """

    def __init__(self) -> None:
        from astromechos_imager.core.models import Role
        # No master_target → single job. role drives channel selection.
        self.role = Role.SLAVE
        self.on_progress = None
        self.cancel_event = threading.Event()

    def run(self):
        from astromechos_imager.core.diskwriter import DiskWriterProgress
        time.sleep(0.05)
        self.on_progress(
            DiskWriterProgress(
                phase="decompress_write",
                bytes_done=100,
                bytes_total=1000,
                throughput_bps=0.0,
            )
        )
        return _FakeSingleResult()


def test_flash_worker_single_slave_job_reports_on_slave_channel(qtbot):
    """Regression: a single FlashJob with role=SLAVE must emit on
    ``progressSlave`` (both the preparing ping AND write chunks), NOT on
    ``progressMaster``. Before the fix the single-job path hard-coded the
    master channel, so the slave-cycle bar — which reads slaveProgress —
    stayed frozen at 0% while the card wrote fine, and operators cancelled a
    working flash."""
    job = _OneChunkSingleSlaveJob()

    master_events, slave_events, thread, _w = _start_worker_and_collect(
        job, is_pair=False, qtbot=qtbot, settle_ms=400
    )
    thread.quit()
    thread.wait(2000)

    assert slave_events, "single SLAVE job emitted nothing on the slave channel"
    assert any(p == "preparing" and f == 0.0 for f, p, t in slave_events), (
        f"slave channel must get the preparing ping; got {slave_events!r}"
    )
    assert any(p == "decompress_write" for f, p, t in slave_events), (
        f"slave channel must get the write progress; got {slave_events!r}"
    )
    assert master_events == [], (
        f"a single SLAVE job must NOT leak onto the master channel; "
        f"got {master_events!r}"
    )


def test_flash_worker_preparing_then_write_phase_sequence(qtbot):
    """Pair flow: the FIRST master event is ``(0.0, "preparing")``;
    a later event must be ``(0.1, "decompress_write")`` once
    ``on_progress`` fires from inside ``job.run()``."""
    job = _OneChunkPairJob()

    master_events, _slave_events, thread, _w = _start_worker_and_collect(
        job, is_pair=True, qtbot=qtbot, settle_ms=400
    )

    # Drain any pending events the QThread may still be flushing.
    thread.quit()
    thread.wait(2000)

    assert master_events, "no master events captured at all"
    first = master_events[0]
    assert first == (0.0, "preparing", 0.0), (
        f"first master event must be the preparing ping; got {first!r}"
    )

    write_events = [
        (f, p, t) for f, p, t in master_events if p == "decompress_write"
    ]
    assert write_events, (
        f"expected a decompress_write follow-up after preparing; "
        f"got {master_events!r}"
    )
    # 100 / 1000 = 0.1 fraction (subject to float). _OneChunkPairJob
    # fires a DiskWriterProgress with throughput_bps=0.0 so we don't
    # pin a real number here — the throughput plumbing is exercised
    # in test_flash_view_model_throughput.py.
    frac, phase, _t = write_events[0]
    assert phase == "decompress_write"
    assert abs(frac - 0.1) < 1e-6, f"expected 0.1 fraction, got {frac}"
