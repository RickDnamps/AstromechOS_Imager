# tests/unit/test_force_unmount_checked.py
"""force_unmount_letter must CHECK DeleteVolumeMountPointW's result.

Field log 2026-06-12: the scan-time letter strip runs ~3 s after card
insertion, racing AutoPlay's probe. DeleteVolumeMountPointW signals
failure with a FALSE return — not an exception — so the previous
``contextlib.suppress(Exception)`` could never notice. A letter binding
that silently survives the strip re-attaches on the next volume arrival
(the sticky-binding "Format this disk?" pop-up). The fix: route through
``_delete_mount_point`` (checked + logged), retry 3 times, and WARN
loudly if the binding survives.

All Win32 surfaces are monkeypatched — no real volume is ever touched
(the conftest sentinel also forbids real mountvol/diskpart).
"""
import logging
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="exercises the Windows platform module",
)


@pytest.fixture
def win(monkeypatch):
    from astromechos_imager.platform import windows

    # No volume handle → the FSCTL lock/dismount block is skipped entirely.
    monkeypatch.setattr(
        windows, "_open_volume_handle",
        lambda path: windows.INVALID_HANDLE_VALUE)
    monkeypatch.setattr(
        windows, "_notify_shell_drive_removed", lambda letter: None)
    monkeypatch.setattr(windows.time, "sleep", lambda s: None)
    return windows


def test_delete_failure_warns_and_retries(win, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(
        win, "_delete_mount_point",
        lambda letter: (calls.append(letter), False)[1])

    with caplog.at_level(logging.WARNING):
        assert win.force_unmount_letter("K") is True   # still best-effort

    assert calls == ["K", "K", "K"], (
        f"expected 3 delete attempts before giving up, got {calls!r}")
    assert any(
        "still failing" in rec.message for rec in caplog.records
    ), "a surviving letter binding must produce a WARNING, not silence"


def test_delete_success_first_try_no_warning(win, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(
        win, "_delete_mount_point",
        lambda letter: (calls.append(letter), True)[1])

    with caplog.at_level(logging.WARNING):
        assert win.force_unmount_letter("K") is True

    assert calls == ["K"], "success on attempt 1 must not retry"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_delete_success_after_transient_failure(win, monkeypatch, caplog):
    results = iter([False, True])
    calls = []

    def fake_delete(letter):
        calls.append(letter)
        return next(results)

    monkeypatch.setattr(win, "_delete_mount_point", fake_delete)

    with caplog.at_level(logging.WARNING):
        assert win.force_unmount_letter("K") is True

    assert calls == ["K", "K"]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "a transient failure recovered by retry must stay quiet")


def test_invalid_letter_rejected(win):
    assert win.force_unmount_letter("") is False
    assert win.force_unmount_letter("KL") is False
    assert win.force_unmount_letter("5") is False
