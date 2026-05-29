"""JSONL log formatter and session log rotation for AstromechOS Imager.

Writes one JSON line per log record to a session file under
``%APPDATA%\\AstromechOS Imager\\logs\\``.  Rotation policy: keep the 20
most-recent session files and delete any older ones on each startup.
"""
from __future__ import annotations

import json
import logging
import os
import traceback as tb_module
from datetime import UTC, datetime
from pathlib import Path


class JsonLineFormatter(logging.Formatter):
    """Format a :class:`logging.LogRecord` as a single JSON line (JSONL).

    Output fields
    -------------
    ``ts``
        UTC ISO 8601 timestamp with millisecond precision (``Z`` suffix).
    ``lvl``
        Level name (e.g. ``"INFO"``, ``"ERROR"``).
    ``mod``
        Logger name (dotted module path or root logger name).
    ``msg``
        Formatted message string.
    ``ctx``
        Optional dict attached by the caller as ``record.ctx``.
    ``exc``
        Full traceback string when the record carries exc_info.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Return the log record serialised as a single UTF-8 JSON line."""
        now = datetime.fromtimestamp(record.created, tz=UTC)
        # e.g. 2026-05-29T02:15:01.234Z
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

        obj: dict[str, object] = {
            "ts": ts,
            "lvl": record.levelname,
            "mod": record.name,
            "msg": record.getMessage(),
        }

        ctx = getattr(record, "ctx", None)
        if ctx is not None:
            obj["ctx"] = ctx

        if record.exc_info:
            obj["exc"] = tb_module.format_exception(*record.exc_info)

        return json.dumps(obj, ensure_ascii=False, default=str)


class LogRotationManager:
    """Manage session log files under *log_dir*, keeping at most *max_files*.

    Each call to :meth:`open_session_log` creates a new file named
    ``flash-<ISO8601>.log`` (colons replaced with hyphens for NTFS
    compatibility).  If the directory already contains more than
    ``max_files`` log files the oldest are deleted first.
    """

    def __init__(self, log_dir: Path, max_files: int = 20) -> None:
        self.log_dir = log_dir
        self.max_files = max_files

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_session_log(self, session_id: str | None = None) -> Path:
        """Return the path to a newly-created session log file.

        Rotates old files (deletes oldest first) so that *at most*
        ``max_files`` remain after this call completes.

        Parameters
        ----------
        session_id:
            Optional override for the timestamp portion of the filename.
            Useful in tests to produce deterministic names.  When *None*
            the current UTC time is used.
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._rotate()

        if session_id is None:
            now = datetime.now(UTC)
            session_id = now.strftime("%Y-%m-%dT%H-%M-%S.") + f"{now.microsecond // 1000:03d}Z"

        log_path = self.log_dir / f"flash-{session_id}.log"
        log_path.touch()
        return log_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _existing_logs(self) -> list[Path]:
        """Return existing ``flash-*.log`` files sorted oldest-first."""
        files = sorted(self.log_dir.glob("flash-*.log"), key=lambda p: p.stat().st_mtime)
        return files

    def _rotate(self) -> None:
        """Delete oldest session logs so that fewer than *max_files* remain."""
        existing = self._existing_logs()
        # We're about to add one new file, so purge until len < max_files.
        while len(existing) >= self.max_files:
            oldest = existing.pop(0)
            try:
                oldest.unlink()
            except OSError:
                pass  # Best-effort; skip if already gone


def setup_logging(
    log_dir: Path | None = None,
    level: int = logging.INFO,
    redact: bool = True,
) -> Path:
    """Wire the root logger with :class:`JsonLineFormatter` and optional redaction.

    Creates a new session log file, attaches a :class:`logging.FileHandler`
    to the root logger, and returns the path to that file.

    Parameters
    ----------
    log_dir:
        Directory for session log files.  Defaults to
        ``%APPDATA%\\AstromechOS Imager\\logs\\`` (or ``~/AstromechOS Imager/logs/``
        on non-Windows systems for dev use).
    level:
        Minimum log level for the root logger.
    redact:
        When *True* attach a :class:`~astromechos_imager.logging_setup.redaction.RedactionFilter`
        to the file handler.

    Returns
    -------
    Path
        The path to the active session log file.
    """
    if log_dir is None:
        appdata = os.environ.get("APPDATA") or str(Path.home())
        log_dir = Path(appdata) / "AstromechOS Imager" / "logs"

    manager = LogRotationManager(log_dir)
    log_path = manager.open_session_log()

    formatter = JsonLineFormatter()

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(formatter)

    if redact:
        # Import here to avoid circular imports at module load time.
        from astromechos_imager.logging_setup.redaction import RedactionFilter

        handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    return log_path
