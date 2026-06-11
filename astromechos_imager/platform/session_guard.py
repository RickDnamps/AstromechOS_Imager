"""Single owner of the {app mutex, automount setting, crash marker} triple.

Before this class existed the three pieces were managed independently and
the crash marker conflated "session crashed" with "session active" (audit
defects A2/A4): a second Imager instance saw the first one's marker, ran
``mountvol /E`` under its feet mid-flash, and whichever instance quit first
re-enabled automount for the survivor. The guard makes the protocol explicit:

    acquire()  claim the single-instance mutex FIRST; only when no live
               instance holds it can a present marker mean "crashed session"
               -> repair (/E) then arm the defense (/N).
    release()  re-enable automount + clear the marker (marker is kept when
               /E fails, see enable_automount) - never called when another
               instance owns the session.

Windows-only in production; the ``win``/``claim_mutex`` constructor seams let
unit tests (and non-Windows platforms) run without touching the real Mount
Manager or kernel mutex namespace.
"""
from __future__ import annotations

import logging
import sys

_log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183

MUTEX_NAME = "Global\\AstromechOS_Imager_AppMutex"


class AutomountSessionGuard:
    """Owns the machine-wide automount state for one Imager session."""

    def __init__(self, *, win=None, claim_mutex=None) -> None:
        self.already_running = False
        self.defense_active = False
        self._mutex_handle = None
        self._released = False
        if win is None:
            from astromechos_imager.platform import windows as win  # noqa: PLC0415
        self._win = win
        if claim_mutex is not None:
            self._claim = claim_mutex
        elif getattr(sys, "frozen", False):
            # Frozen builds claim the real kernel mutex (the Inno Setup
            # installer checks the same name via AppMutex=). Dev runs and
            # pytest skip it: build_app() is called repeatedly in one pytest
            # process and the second CreateMutexW would see
            # ERROR_ALREADY_EXISTS from the FIRST call's still-open handle.
            self._claim = self._claim_mutex_win32
        else:
            self._claim = lambda: (None, False)

    def _claim_mutex_win32(self):
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        already = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
        return handle, already

    def acquire(self) -> bool:
        """Claim the session. Returns True when the automount defense is armed.

        When another live instance holds the mutex, sets ``already_running``
        and returns False WITHOUT having touched any machine state - the
        caller must inform the operator and exit.
        """
        self._mutex_handle, self.already_running = self._claim()
        if self.already_running:
            _log.warning(
                "another Imager instance is running - leaving its automount "
                "session untouched"
            )
            return False
        # No live instance -> a present marker really means a crashed
        # session: repair it, then arm the defense for THIS session.
        self._win.restore_automount_if_crashed()
        self.defense_active = bool(self._win.disable_automount())
        return self.defense_active

    def release(self) -> bool:
        """Re-enable automount at clean exit. Idempotent."""
        if self.already_running:
            return False  # never touch the other instance's session
        if self._released:
            return True
        ok = bool(self._win.enable_automount())
        self._released = ok
        return ok
