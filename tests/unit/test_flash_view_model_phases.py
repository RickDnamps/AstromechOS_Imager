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
    - regression that routes a slave-role job to the master channel
    - regression that drops the determinate ``decompress_write`` follow-up

(The pair variants died with PairFlashJob — production is sequential,
one single-role job per cycle.)
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


class _FakeSingleResult:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.error = None if ok else "boom"


class _BlockingSingleJob:
    """Single-role job whose ``run()`` blocks until ``release_event`` is set.

    Lets the test observe that the worker emits ``preparing`` BEFORE
    ``run()`` does any work — i.e. the emit happens at thread entry, not
    as a side-effect of ``on_progress`` callbacks.
    """

    def __init__(self, release_event: threading.Event,
                 role_value: str = "master") -> None:
        from astromechos_imager.core.models import Role
        self.role = Role.MASTER if role_value == "master" else Role.SLAVE
        self.on_progress = None
        self.cancel_event = threading.Event()
        self._release = release_event

    def run(self):
        self._release.wait(timeout=5.0)
        return _FakeSingleResult()


class _OneChunkSingleJob:
    """Master-role job that fires exactly one ``decompress_write`` chunk,
    lets the worker drain, then returns success.

    Used to lock the sequence: ``preparing`` arrives FIRST, the real
    write phase arrives SECOND.
    """

    def __init__(self) -> None:
        from astromechos_imager.core.models import Role
        self.role = Role.MASTER
        self.on_progress = None
        self.cancel_event = threading.Event()

    def run(self):
        from astromechos_imager.core.diskwriter import DiskWriterProgress
        # Give the QThread event loop a chance to deliver the "preparing"
        # emit to the main-thread connections before we fire the next
        # phase — otherwise both emits race and the order assertion is
        # flaky.
        time.sleep(0.05)
        self.on_progress(
            DiskWriterProgress(
                phase="decompress_write",
                bytes_done=100,
                bytes_total=1000,
                throughput_bps=0.0,
            ),
        )
        return _FakeSingleResult()


# ─── Helpers ──────────────────────────────────────────────────────────


def _start_worker_and_collect(job, qtbot, settle_ms: int = 200):
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
    master_events: list[tuple[float, str, float]] = []
    slave_events: list[tuple[float, str, float]] = []

    thread = QThread()
    worker = _FlashWorker(job)
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


def test_flash_worker_emits_preparing_phase_immediately_single(qtbot):
    """``progressMaster`` must receive ``(0.0, "preparing", 0.0)`` BEFORE
    ``job.run()`` returns."""
    release = threading.Event()
    job = _BlockingSingleJob(release)

    master_events, slave_events, thread, _w = _start_worker_and_collect(
        job, qtbot=qtbot
    )

    assert any(
        p == "preparing" and f == 0.0 and t == 0.0 for f, p, t in master_events
    ), (
        f"expected (0.0, 'preparing', 0.0) in master events before "
        f"job.run() returned; got {master_events!r}"
    )
    assert slave_events == [], (
        "a MASTER-role job must not touch the slave channel"
    )

    release.set()
    thread.quit()
    thread.wait(2000)


def test_flash_worker_single_slave_job_reports_on_slave_channel(qtbot):
    """A SLAVE-role job's preparing ping must land on ``progressSlave`` —
    the role-aware routing regression left the slave bar frozen at 0%."""
    release = threading.Event()
    job = _BlockingSingleJob(release, role_value="slave")

    master_events, slave_events, thread, _w = _start_worker_and_collect(
        job, qtbot=qtbot
    )

    assert any(p == "preparing" for _f, p, _t in slave_events), (
        f"expected the preparing ping on the SLAVE channel; got "
        f"slave={slave_events!r} master={master_events!r}"
    )
    assert master_events == []

    release.set()
    thread.quit()
    thread.wait(2000)


def test_flash_worker_preparing_then_write_phase_sequence(qtbot):
    """Order contract: ``preparing`` first, ``decompress_write`` second."""
    job = _OneChunkSingleJob()

    master_events, _slave_events, thread, _w = _start_worker_and_collect(
        job, qtbot=qtbot, settle_ms=400
    )

    phases = [p for _f, p, _t in master_events]
    assert "preparing" in phases and "decompress_write" in phases, (
        f"expected both phases; got {phases!r}"
    )
    assert phases.index("preparing") < phases.index("decompress_write"), (
        f"'preparing' must precede 'decompress_write'; got {phases!r}"
    )

    thread.quit()
    thread.wait(2000)
