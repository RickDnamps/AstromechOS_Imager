"""ctypes bridge to astro_flash.dll's Phase 0 "tame the shell" surface.

Phase 0 exports a device-less subset of the native flash core:

    astro_version()              -> str
    astro_quiet_thread()         -> sets THIS thread's error mode
    astro_lock_and_quiet(csv)    -> dismount + DeleteVolumeMountPoint +
                                    SHChangeNotify(MEDIA/DRIVE REMOVED) for
                                    each letter, plus astro_quiet_thread

These are the two mechanisms the pure-Python path never did:
  1. SetThreadErrorMode in the *worker* thread (not just at app boot in
     the Qt main thread).
  2. SHChangeNotify, the proactive "this drive is gone" signal that stops
     Explorer polling the device and rendering the "Format K:?" pop-up.

The DLL is resolved from the ``vendor/`` directory via
``core.vendored_binaries.vendor_root()``. When the DLL is absent (dev box
without a build, or non-Windows), every function here degrades to a no-op
that returns False/"" so callers can stay unconditional.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

_log = logging.getLogger(__name__)


# ── AstroStatus struct (must match astro_flash.h byte-for-byte) ────────
class _AstroStatus(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_int32),
        ("win_error", ctypes.c_uint32),
        ("message", ctypes.c_char * 256),
    ]


_dll: ctypes.CDLL | None = None
_load_attempted = False


def _dll_path() -> Path:
    from astromechos_imager.core.vendored_binaries import vendor_root
    return vendor_root() / "astro_flash.dll"


def _load() -> ctypes.CDLL | None:
    """Load astro_flash.dll once; cache the handle. None if unavailable."""
    global _dll, _load_attempted
    if _load_attempted:
        return _dll
    _load_attempted = True
    if not sys.platform.startswith("win"):
        return None
    p = _dll_path()
    if not p.is_file():
        _log.info("astro_flash.dll not present at %s -- native shell-quiet disabled", p)
        return None
    try:
        dll = ctypes.CDLL(str(p))
        dll.astro_version.restype = ctypes.c_char_p
        dll.astro_quiet_thread.argtypes = [ctypes.POINTER(_AstroStatus)]
        dll.astro_quiet_thread.restype = ctypes.c_int
        dll.astro_lock_and_quiet.argtypes = [
            ctypes.c_char_p, ctypes.POINTER(_AstroStatus),
        ]
        dll.astro_lock_and_quiet.restype = ctypes.c_int
        _dll = dll
        ver = dll.astro_version().decode("ascii", "replace")
        _log.info("astro_flash.dll loaded: %s", ver)
    except OSError as exc:
        _log.warning("astro_flash.dll failed to load (%s) -- native shell-quiet disabled", exc)
        _dll = None
    return _dll


def available() -> bool:
    """True iff the native DLL is loaded and usable."""
    return _load() is not None


def version() -> str:
    dll = _load()
    if dll is None:
        return ""
    return dll.astro_version().decode("ascii", "replace")


def quiet_thread() -> bool:
    """Set the CURRENT thread's error mode (suppress shell error dialogs).

    Call from the flash worker thread before raw device I/O. Returns True
    on success, False if the DLL is unavailable or the call failed.
    """
    dll = _load()
    if dll is None:
        return False
    st = _AstroStatus()
    rc = dll.astro_quiet_thread(ctypes.byref(st))
    if rc != 0:
        _log.warning("astro_quiet_thread failed: code=%d win_error=%d msg=%s",
                     st.code, st.win_error, st.message.decode("ascii", "replace"))
        return False
    return True


def lock_and_quiet(drive_letters: tuple[str, ...] | list[str] | str) -> bool:
    """Run the full native quiet dance for the given drive letter(s).

    Accepts a tuple/list of single-letter strings ("K",) or a raw CSV
    string ("K" / "K,L"). Returns True on success (best-effort — the
    native side never hard-fails on a single letter), False if the DLL
    is unavailable.
    """
    dll = _load()
    if dll is None:
        return False
    if isinstance(drive_letters, str):
        csv = drive_letters
    else:
        csv = ",".join(drive_letters)
    st = _AstroStatus()
    rc = dll.astro_lock_and_quiet(csv.encode("ascii", "replace"), ctypes.byref(st))
    if rc != 0:
        _log.warning("astro_lock_and_quiet(%s) failed: code=%d win_error=%d msg=%s",
                     csv, st.code, st.win_error, st.message.decode("ascii", "replace"))
        return False
    _log.info("astro_lock_and_quiet(%s) OK (native shell-quiet applied)", csv)
    return True
