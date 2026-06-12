"""End-to-end throughput plumbing tests for the live "X.X Mo/s" badge.

Pin the DiskWriter → FlashViewModel → QML contract:

  1. ``_FlashWorker.progressMaster`` is a 3-arg Signal carrying
     ``(fraction, phase, throughput_bps)``.
  2. ``FlashViewModel.masterThroughputBps`` updates whenever the
     worker emits and exposes the latest sample to QML.
  3. ``_begin_verify_phase`` resets throughput to 0 so the
     ``GlobalProgressBar`` badge disappears between cycles instead
     of leaking the previous flash's last sample into the verify
     phase header.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_vm():
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    from astromechos_imager.ui.wizard_state import WizardState
    return FlashViewModel(WizardState())


# ── Tests ─────────────────────────────────────────────────────────────


def test_progressMaster_emits_throughput_third_arg(qtbot):
    """``_FlashWorker._on_single_progress`` must forward the
    ``DiskWriterProgress.throughput_bps`` field as the THIRD argument
    of ``progressMaster``. Two-arg consumers would silently drop it."""
    from astromechos_imager.core.diskwriter import DiskWriterProgress
    from astromechos_imager.core.models import Role
    from astromechos_imager.ui.flash_view_model import _FlashWorker

    captured: list[tuple[float, str, float]] = []

    class _MasterJob:
        role = Role.MASTER

    # The worker doesn't need to actually run() for this test — we're
    # exercising the callback directly to bypass QThread scheduling.
    worker = _FlashWorker(job=_MasterJob())
    worker.progressMaster.connect(
        lambda f, p, t: captured.append((f, p, t))
    )

    worker._on_single_progress(
        DiskWriterProgress(
            phase="decompress_write",
            bytes_done=512,
            bytes_total=1024,
            throughput_bps=50_000_000.0,
        ),
    )

    # Qt may queue the signal; in the same thread we hand it off via
    # AutoConnection which collapses to Direct.
    assert captured == [(0.5, "decompress_write", 50_000_000.0)], (
        f"expected the throughput to ride along as the 3rd signal arg; "
        f"got {captured!r}"
    )


def test_masterThroughputBps_property_updates_after_emit(qtbot):
    """Driving ``_update_master`` with a throughput value must update
    the ``masterThroughputBps`` Property and fire its Changed signal so
    QML re-binds the GlobalProgressBar's "X.X Mo/s" badge."""
    vm = _make_vm()

    changed_count = [0]
    vm.masterThroughputBpsChanged.connect(
        lambda: changed_count.__setitem__(0, changed_count[0] + 1)
    )

    vm._update_master(0.5, "decompress_write", 50_000_000.0)

    assert vm.masterThroughputBps == 50_000_000.0, (
        f"masterThroughputBps must reflect the most recent worker emit; "
        f"got {vm.masterThroughputBps!r}"
    )
    assert changed_count[0] >= 1, (
        "masterThroughputBpsChanged must fire so QML rebinds"
    )


def test_slaveThroughputBps_property_updates_after_emit(qtbot):
    """Symmetric: same contract for the slave channel — pair-mode
    flashes must not leave the slave half of the UI on a stale value."""
    vm = _make_vm()

    vm._update_slave(0.25, "decompress_write", 12_345_678.0)

    assert vm.slaveThroughputBps == 12_345_678.0


def test_masterThroughputBps_resets_to_zero_at_verify_phase_start(qtbot):
    """A new ``_begin_verify_phase`` (e.g. operator hits WRITE for a
    second card) must wipe the throughput so the GlobalProgressBar's
    "Mo/s" badge disappears during the hash phase instead of carrying
    the previous flash's terminal speed sample."""
    vm = _make_vm()

    # Seed a non-zero throughput as if a previous flash had just ended.
    vm._update_master(1.0, "verify", 75_000_000.0)
    assert vm.masterThroughputBps == 75_000_000.0

    # Provide a dummy "job" — _begin_verify_phase only stores it for
    # later use by _spawn_next_hash_worker; we don't drive that here.
    class _DummyJob:
        pass

    # _spawn_next_hash_worker reads wizard_state.currentRole +
    # masterImagePath; the WizardState defaults give us a usable role
    # but no image path, so we patch the queue spawner to a no-op.
    vm._spawn_next_hash_worker = lambda: None  # type: ignore[assignment]

    vm._begin_verify_phase(_DummyJob())

    assert vm.masterThroughputBps == 0.0, (
        f"_begin_verify_phase must reset masterThroughputBps to 0.0 so "
        f"the GlobalProgressBar Mo/s badge hides during hash verify; "
        f"got {vm.masterThroughputBps!r}"
    )
    assert vm.slaveThroughputBps == 0.0


def test_diskwriter_throughput_field_is_carried_via_dataclass(qtbot):
    """Smoke check on the dataclass: a non-zero throughput round-trips
    untouched through the worker callback into the FlashViewModel."""
    from astromechos_imager.core.diskwriter import DiskWriterProgress
    from astromechos_imager.core.models import Role
    from astromechos_imager.ui.flash_view_model import _FlashWorker

    class _SlaveJob:
        role = Role.SLAVE

    vm = _make_vm()
    worker = _FlashWorker(job=_SlaveJob())
    worker.progressMaster.connect(vm._update_master)
    worker.progressSlave.connect(vm._update_slave)

    worker._on_single_progress(
        DiskWriterProgress(
            phase="verify",
            bytes_done=999,
            bytes_total=1000,
            throughput_bps=42_000_000.5,
        ),
    )

    # Slave routed correctly; master untouched.
    assert vm.slaveThroughputBps == pytest.approx(42_000_000.5)
    assert vm.masterThroughputBps == 0.0
