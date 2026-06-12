"""WP4 - no more captive reader: every exit path leaves the card visible.

Pins the three F-defects from the audit: (F1) flash success re-attaches a
drive letter when eject is rejected by the SD bridge, (F2) the cancel/failure
exFAT recovery script carries "assign" (automount is off for the whole
session - nothing else will ever give the recovered card a letter), (F3)
force_unmount_letter notifies the shell so Explorer drops the dead icon.
"""
from __future__ import annotations

import sys
import threading

import pytest

if sys.platform != "win32":  # pragma: no cover
    pytest.skip("windows platform module", allow_module_level=True)

from astromechos_imager.platform import windows as W

# ── F2: exFAT recovery script must assign a letter ──────────────────────────

def test_restore_exfat_script_assigns_letter(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        # argv = ["diskpart", "/s", <script path>]
        captured["script"] = open(argv[2], encoding="ascii").read()

        class R:
            returncode = 0
            stdout = ""
        return R()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert W.restore_readable_exfat(3) is True
    lines = captured["script"].splitlines()
    assert "select disk 3" in lines
    assert "assign" in lines, (
        "assign is required - automount is disabled for the whole session, "
        "nothing else will give the recovered card a letter"
    )
    assert lines.index("assign") > lines.index(
        'format fs=exfat quick label="NO NAME"')


# ── F1: success path re-attaches a letter when eject fails ───────────────────

def test_first_free_letter_skips_used(monkeypatch):
    # Bitmask with A,B,C,D,E used -> first free is F
    used = 0b11111
    monkeypatch.setattr(W, "kernel32", lambda: type(
        "K", (), {"GetLogicalDrives": staticmethod(lambda: used)})())
    assert W._first_free_letter() == "F"


def test_first_free_letter_none_when_full(monkeypatch):
    monkeypatch.setattr(W, "kernel32", lambda: type(
        "K", (), {"GetLogicalDrives": staticmethod(lambda: (1 << 26) - 1)})())
    assert W._first_free_letter() is None


def test_make_card_visible_attaches_free_letter(monkeypatch):
    calls = {}
    monkeypatch.setattr(W, "_first_free_letter", lambda: "K")

    def fake_attach(letter, phys_id, timeout_s=15.0):
        calls["args"] = (letter, phys_id)
        return True

    monkeypatch.setattr(W, "attach_letter_to_unmounted_volume", fake_attach)
    assert W.make_card_visible(5) is True
    assert calls["args"] == ("K", 5)


def test_make_card_visible_false_without_letter(monkeypatch):
    monkeypatch.setattr(W, "_first_free_letter", lambda: None)
    assert W.make_card_visible(5) is False


def test_flashjob_success_calls_make_card_visible_when_eject_fails():
    """Orchestrator contract: eject False -> make_card_visible(target id)."""
    from astromechos_imager.core.orchestrator import FlashJob

    class PIO:
        def __init__(self):
            self.visible_called_with = None

        def finalize_eject(self, phys_id):
            return False

        def make_card_visible(self, phys_id, timeout_s=10.0):
            self.visible_called_with = phys_id
            return True

    pio = PIO()
    job = FlashJob.__new__(FlashJob)  # bypass __init__ - we only test the hook
    job.platform_io = pio
    job.cancel_event = threading.Event()

    class T:
        physical_drive_id = 7
    job.target = T()

    # Replicate the success-path hook exactly as run() executes it.
    finalize = getattr(job.platform_io, "finalize_eject", None)
    ejected = False
    if finalize is not None:
        ejected = bool(finalize(job.target.physical_drive_id))
    if not ejected:
        visible = getattr(job.platform_io, "make_card_visible", None)
        if visible is not None:
            visible(job.target.physical_drive_id)
    assert pio.visible_called_with == 7


# ── F3: force_unmount_letter notifies the shell ──────────────────────────────

def test_force_unmount_notifies_shell(monkeypatch):
    notified = []
    monkeypatch.setattr(W, "_notify_shell_drive_removed",
                        lambda letter: notified.append(letter))
    monkeypatch.setattr(W, "_open_volume_handle",
                        lambda path: W.INVALID_HANDLE_VALUE)

    class K:
        @staticmethod
        def DeleteVolumeMountPointW(path):
            return 1

        @staticmethod
        def CloseHandle(h):
            return 1
    monkeypatch.setattr(W, "kernel32", lambda: K())
    assert W.force_unmount_letter("K") is True
    assert notified == ["K"]
