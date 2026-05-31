"""Redaction filter for AstromechOS Imager session logs.

Prevents sensitive material from appearing in JSONL log files by mutating
``record.ctx`` in-place before the record is written.

Fields redacted (replaced, never dropped so callers know the key existed):
- Any ``ctx`` key matching ``*private*`` whose value is a string containing
  the OpenSSH private-key header — replaced with a SHA-256 fingerprint.
- Any ``ctx`` key matching ``*private*`` — replaced with a SHA-256 fingerprint
  (covers ed25519 private key bytes regardless of header).
- ``cleartext_password`` or any key containing ``cleartext_password`` or
  ``linux_password`` — replaced with ``"<redacted: password>"``.
- Any ``ctx`` key matching ``*psk*`` or ``*hotspot_password*`` —
  replaced with a SHA-256 fingerprint of the value.
- ``authorized_keys`` (list of str) — replaced with a fingerprint summary.
- ``bytes`` values > 256 bytes — replaced with ``"<N bytes>"``.
- File-path strings containing a Windows username segment
  (``C:\\Users\\<name>\\...``) — truncated to basename only.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path, PureWindowsPath


_OPENSSH_PRIVATE_HEADER = "-----BEGIN OPENSSH PRIVATE KEY-----"

# Regex to detect Windows user paths: C:\Users\<something>\...
_WIN_USER_PATH_RE = re.compile(
    r"[A-Za-z]:\\[Uu]sers\\[^\\]+\\",
    re.IGNORECASE,
)

# Audit bug Sec1: free-text log messages can leak SSID / PSK / password
# values that never travelled through ``record.ctx``. The classic
# offender is FlashViewModel.startSession which logged
# ``Sequential session started — hotspot SSID=Astromech-1234`` —
# bypassing every ctx-keyed scrub above. These patterns are applied to
# ``record.msg`` (and its formatted result) inside RedactionFilter so
# the JSONL formatter never sees the raw secret.
_LEAK_PATTERNS = [
    (re.compile(r"(SSID\s*=\s*)([^\s,()]+)", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(psk\s*=\s*)([^\s,()]+)", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(password\s*=\s*)([^\s,()]+)", re.IGNORECASE), r"\1<redacted>"),
    # Bare Astromech-NNNN literal anywhere in the message (no key=val context).
    (re.compile(r"\bAstromech-\d{4}\b"), "<redacted-SSID>"),
]


def _sha256_fingerprint(value: object) -> str:
    """Return a short SHA-256 fingerprint string for *value*.

    Uses the first 12 hex characters of the digest, prefixed with
    ``sha256:`` — sufficient to cross-reference without exposing the secret.
    """
    if isinstance(value, (bytes, bytearray)):
        raw = value
    else:
        raw = str(value).encode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest[:12]}"


def _is_private_key(value: object) -> bool:
    """Return True if *value* appears to be an SSH private key string."""
    if isinstance(value, str):
        return _OPENSSH_PRIVATE_HEADER in value
    if isinstance(value, (bytes, bytearray)):
        try:
            return _OPENSSH_PRIVATE_HEADER in value.decode("ascii", errors="ignore")
        except Exception:
            return False
    return False


def _redact_authorized_keys(value: object) -> str:
    """Replace a list of authorized_keys entries with a fingerprint summary."""
    if isinstance(value, list):
        count = len(value)
        fps = []
        for entry in value:
            if isinstance(entry, str):
                fps.append(_sha256_fingerprint(entry))
        if fps:
            fps_str = ", ".join(fps)
            return f"<{count} keys, fingerprints: {fps_str}>"
        return f"<{count} keys>"
    # If it's a raw string blob, count lines
    if isinstance(value, str):
        lines = [ln for ln in value.splitlines() if ln.strip()]
        count = len(lines)
        fps = [_sha256_fingerprint(ln) for ln in lines]
        if fps:
            return f"<{count} keys, fingerprints: {', '.join(fps)}>"
        return f"<{count} keys>"
    return f"<redacted: authorized_keys, fp={_sha256_fingerprint(value)}>"


def _redact_path(value: str) -> str:
    """Strip the Windows user segment from file paths, returning basename only."""
    if _WIN_USER_PATH_RE.search(value):
        # Use PureWindowsPath to safely extract the last component
        try:
            return PureWindowsPath(value).name
        except Exception:
            return Path(value).name
    return value


def _redact_value(key: str, value: object) -> object:
    """Return a redacted replacement for *value* based on the *key* name."""
    key_lower = key.lower()

    # --- bytes blobs > 256 B ------------------------------------------------
    if isinstance(value, (bytes, bytearray)) and len(value) > 256:
        return f"<{len(value)} bytes>"

    # --- Password fields (linux password / cleartext password) ---------------
    if "cleartext_password" in key_lower or "linux_password" in key_lower:
        return "<redacted: password>"

    # --- Private key fields --------------------------------------------------
    if "private" in key_lower:
        fp = _sha256_fingerprint(value)
        return f"<redacted: ed25519 private, fp={fp}>"

    # --- PSK / hotspot password fields --------------------------------------
    if "psk" in key_lower or "hotspot_password" in key_lower:
        fp = _sha256_fingerprint(value)
        return f"<redacted: WPA2-PSK, fp={fp}>"

    # --- authorized_keys ----------------------------------------------------
    if key_lower == "authorized_keys":
        return _redact_authorized_keys(value)

    # --- String value checks (private key content, paths) -------------------
    if isinstance(value, str):
        if _is_private_key(value):
            fp = _sha256_fingerprint(value)
            return f"<redacted: ed25519 private, fp={fp}>"
        if _WIN_USER_PATH_RE.search(value):
            return _redact_path(value)

    return value


def _redact_ctx(ctx: dict) -> dict:  # type: ignore[type-arg]
    """Return a new dict with all sensitive values replaced."""
    return {k: _redact_value(k, v) for k, v in ctx.items()}


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs sensitive fields from ``record.ctx``.

    Mutates ``record.ctx`` in-place (replacing it with a sanitised copy).
    Always returns ``True`` so the record is never suppressed — only cleaned.

    Sensitive patterns handled:
    - ``*private*`` keys → SHA-256 fingerprint placeholder
    - ``cleartext_password`` / ``linux_password`` keys → ``"<redacted: password>"``
    - ``*psk*`` / ``*hotspot_password*`` keys → SHA-256 fingerprint placeholder
    - ``authorized_keys`` → fingerprint summary
    - ``bytes`` > 256 → ``"<N bytes>"``
    - File paths with Windows username → basename only
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        """Redact sensitive fields in *record.ctx*; always allow the record through.

        Audit bug Sec1: also scrub ``record.msg`` for SSID / PSK /
        password key=value patterns and bare ``Astromech-NNNN``
        literals. Without this, callers that put secrets in the log
        message text bypass every ctx-keyed rule above.
        """
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            record.ctx = _redact_ctx(ctx)  # type: ignore[attr-defined]

        # Free-text message scrub. Use getMessage() to resolve %-args
        # then reset msg+args so downstream formatters and handlers see
        # the cleaned string. Skip when msg is not a string (e.g. when
        # callers pass an exception/dict directly).
        if isinstance(record.msg, str):
            try:
                msg = record.getMessage()
            except Exception:  # noqa: BLE001
                # If %-formatting blew up, fall back to the raw template.
                msg = record.msg
            changed = False
            for pat, rep in _LEAK_PATTERNS:
                new_msg = pat.sub(rep, msg)
                if new_msg != msg:
                    changed = True
                    msg = new_msg
            if changed:
                record.msg = msg
                record.args = ()
        return True
