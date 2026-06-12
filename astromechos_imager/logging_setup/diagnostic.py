"""Diagnostic ZIP export for AstromechOS Imager.

Assembles a support bundle (ZIP file) containing:
- ``session.log``      — the active JSONL session log
- ``traceback.txt``    — most-recent exception traceback
- ``system_info.json`` — safe OS/Python/arch metadata (no username, no hostname)
- ``firstboot_config.json`` — already-redacted firstboot config (PSK stripped
                               unless the caller opts in with ``include_psk=True``)

Double-redaction guarantee:  even if the caller forgets to redact sensitive
fields before passing *firstboot_config*, this module strips ``hotspot_password``
and ``cleartext_password`` keys from the dict before writing to the ZIP.
"""
from __future__ import annotations

import json
import platform
import sys
import zipfile
from pathlib import Path

import astromechos_imager  # noqa: F401 — imported for __version__ access

# Keys stripped from firstboot_config unless include_psk=True
_PSK_KEYS = frozenset({"hotspot_password", "password"})

# Keys always stripped from firstboot_config (passwords never in diagnostic)
_ALWAYS_STRIP_KEYS = frozenset({"cleartext_password", "linux_password"})


def _sanitise_firstboot_config(cfg: dict, *, include_psk: bool) -> dict:  # type: ignore[type-arg]
    """Return a copy of *cfg* with sensitive keys removed.

    Always strips:
    - ``cleartext_password`` — Linux user password
    - ``linux_password``     — alternative spelling

    Strips unless *include_psk* is True:
    - ``hotspot_password``   — WPA2 bootstrap PSK
    - ``password`` (under any [hotspot] section dict)

    The function recurses into nested dicts (e.g. a ``hotspot`` section dict).
    """
    result: dict = {}  # type: ignore[type-arg]
    for k, v in cfg.items():
        k_lower = k.lower()
        # Always strip password fields
        if any(stripped in k_lower for stripped in _ALWAYS_STRIP_KEYS):
            continue
        # Strip PSK fields unless caller opted in
        if not include_psk and any(psk_key in k_lower for psk_key in _PSK_KEYS):
            continue
        # Recurse into nested dicts
        if isinstance(v, dict):
            result[k] = _sanitise_firstboot_config(v, include_psk=include_psk)
        else:
            result[k] = v
    return result


def collect_system_info() -> dict:  # type: ignore[type-arg]
    """Return diagnostic-safe system metadata.

    Includes:
    - ``os``        — OS description from :mod:`platform`
    - ``os_release`` — release string (e.g. ``"10"`` or ``"11"``)
    - ``arch``      — machine architecture (e.g. ``"AMD64"``)
    - ``python``    — Python version string
    - ``app_version`` — AstromechOS Imager package version

    Deliberately excludes ``%USERNAME%``, ``%COMPUTERNAME%``, hostname, and
    any file-system path that could identify the user.
    """
    try:
        app_version = astromechos_imager.__version__  # type: ignore[attr-defined]
    except AttributeError:
        app_version = "unknown"

    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "arch": platform.machine(),
        "python": sys.version,
        "app_version": app_version,
    }


def build_diagnostic_zip(
    target: Path,
    log_path: Path,
    traceback_text: str,
    system_info: dict,  # type: ignore[type-arg]
    firstboot_config: dict,  # type: ignore[type-arg]
    include_psk: bool = False,
) -> None:
    """Write a diagnostic support bundle to *target* (a ``.zip`` file).

    Parameters
    ----------
    target:
        Output ZIP path.  The parent directory must already exist.
    log_path:
        Path to the JSONL session log.  Included as ``session.log`` in the ZIP.
        If the file does not exist a placeholder entry with a note is written.
    traceback_text:
        Most-recent exception traceback (or empty string).  Written as
        ``traceback.txt``.
    system_info:
        Diagnostic system metadata — use :func:`collect_system_info`.
        ``%USERNAME%`` and hostname must NOT appear in this dict; callers are
        responsible for providing a safe dict, but see also
        :func:`collect_system_info` which enforces this.
    firstboot_config:
        Imager-generated firstboot configuration dict, **already redacted** by
        :class:`~astromechos_imager.logging_setup.redaction.RedactionFilter`.
        This function applies a **second layer** of redaction to strip any
        ``hotspot_password`` / ``cleartext_password`` keys that might have
        slipped through.
    include_psk:
        When *True*, the ``hotspot_password`` key is retained in
        ``firstboot_config.json`` (useful for support escalation when the
        operator explicitly consents).  Defaults to *False*.

    Raises
    ------
    OSError
        If *target* cannot be created.
    """
    safe_config = _sanitise_firstboot_config(firstboot_config, include_psk=include_psk)

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # --- session.log ---------------------------------------------------
        if log_path.exists():
            zf.write(log_path, arcname="session.log")
        else:
            zf.writestr("session.log", f"[session log not found: {log_path}]")

        # --- traceback.txt -------------------------------------------------
        zf.writestr("traceback.txt", traceback_text or "(no traceback)")

        # --- system_info.json ----------------------------------------------
        zf.writestr(
            "system_info.json",
            json.dumps(system_info, indent=2, ensure_ascii=False, default=str),
        )

        # --- firstboot_config.json -----------------------------------------
        zf.writestr(
            "firstboot_config.json",
            json.dumps(safe_config, indent=2, ensure_ascii=False, default=str),
        )
