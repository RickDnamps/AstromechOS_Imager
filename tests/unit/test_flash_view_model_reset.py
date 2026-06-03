"""Tests for FlashViewModel.resetForNextCycle() — used by Step 6 continue,
Step 4 NEXT defensive reset, and Step 5 RETRY button after error.

Regression coverage for the "operator stuck after flash error" bug:
the Step 5 RETRY button and Step 4 NEXT defensive reset both call
resetForNextCycle() to flip status back to "idle" so the WRITE/RETRY
flow re-engages without restarting the wizard (and thus preserving
the session SSID across the retry).
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def _make_vm():
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    from astromechos_imager.ui.wizard_state import WizardState
    return FlashViewModel(WizardState())


def test_reset_clears_error_status():
    """After error, resetForNextCycle restores status to idle."""
    vm = _make_vm()
    vm._status = "error"
    vm._error_message = "WriteFile failed"
    vm.resetForNextCycle()
    assert vm._status == "idle"
    assert vm._error_message == ""


def test_reset_clears_progress_and_phases():
    """Reset clears per-cycle progress/phase/throughput state."""
    vm = _make_vm()
    vm._master_progress = 0.5
    vm._master_phase = "writing"
    vm._slave_progress = 0.3
    vm._master_throughput_bps = 12345.0
    vm.resetForNextCycle()
    assert vm._master_progress == 0.0
    assert vm._master_phase == ""
    assert vm._slave_progress == 0.0
    assert vm._master_throughput_bps == 0.0


def test_reset_emits_signals():
    """Reset emits all relevant change signals so QML re-renders."""
    vm = _make_vm()
    vm._status = "error"
    received = {"status": 0, "error": 0}
    vm.statusChanged.connect(lambda: received.__setitem__("status", received["status"] + 1))
    vm.errorMessageChanged.connect(lambda: received.__setitem__("error", received["error"] + 1))
    vm.resetForNextCycle()
    assert received["status"] >= 1
    assert received["error"] >= 1
