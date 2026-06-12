"""WP2 - AutomountSessionGuard: session ownership of the automount triple.

Pins the protocol that kills audit defects A2/A4: a second live instance
must never repair ("mountvol /E") or release the first instance's automount
session, and a present marker only means "crashed" when no instance holds
the mutex. Everything is faked - no kernel mutex, no mountvol.
"""
from __future__ import annotations

from astromechos_imager.platform.session_guard import AutomountSessionGuard


class FakeWin:
    def __init__(self, disable_ok=True, enable_ok=True):
        self.calls = []
        self._disable_ok = disable_ok
        self._enable_ok = enable_ok

    def restore_automount_if_crashed(self):
        self.calls.append("restore")

    def disable_automount(self):
        self.calls.append("disable")
        return self._disable_ok

    def enable_automount(self):
        self.calls.append("enable")
        return self._enable_ok


def _guard(win, already=False):
    return AutomountSessionGuard(win=win, claim_mutex=lambda: (1234, already))


def test_acquire_arms_defense_when_alone():
    win = FakeWin()
    g = _guard(win)
    assert g.acquire() is True
    assert g.already_running is False
    assert g.defense_active is True
    # repair happens BEFORE arming, and only those two calls
    assert win.calls == ["restore", "disable"]


def test_claim_alone_touches_nothing():
    """A6 split: claim() is mutex-only — no mountvol until arm()."""
    win = FakeWin()
    g = _guard(win)
    assert g.claim() is True
    assert win.calls == []
    assert g.arm() is True
    assert win.calls == ["restore", "disable"]


def test_arm_refuses_when_already_running():
    win = FakeWin()
    g = _guard(win, already=True)
    assert g.claim() is False
    assert g.arm() is False
    assert win.calls == []


def test_acquire_second_instance_touches_nothing():
    win = FakeWin()
    g = _guard(win, already=True)
    assert g.acquire() is False
    assert g.already_running is True
    assert win.calls == [], "a second instance must not run any mountvol"


def test_acquire_reports_unarmed_defense():
    win = FakeWin(disable_ok=False)
    g = _guard(win)
    assert g.acquire() is False
    assert g.already_running is False
    assert g.defense_active is False
    assert win.calls == ["restore", "disable"]


def test_release_second_instance_never_enables():
    win = FakeWin()
    g = _guard(win, already=True)
    g.acquire()
    assert g.release() is False
    assert "enable" not in win.calls


def test_release_restores_and_is_idempotent():
    win = FakeWin()
    g = _guard(win)
    g.acquire()
    assert g.release() is True
    assert g.release() is True
    assert win.calls.count("enable") == 1, "release must be idempotent"


def test_release_retries_after_failed_enable():
    win = FakeWin(enable_ok=False)
    g = _guard(win)
    g.acquire()
    assert g.release() is False
    win._enable_ok = True
    assert g.release() is True
    assert win.calls.count("enable") == 2, "a failed /E must stay retryable"
