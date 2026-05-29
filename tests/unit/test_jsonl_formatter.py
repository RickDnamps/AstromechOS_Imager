"""Unit tests for astromechos_imager.logging_setup.jsonl_formatter."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pytest

from astromechos_imager.logging_setup.jsonl_formatter import (
    JsonLineFormatter,
    LogRotationManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    msg: str = "hello",
    level: int = logging.INFO,
    name: str = "diskwriter",
    ctx: dict | None = None,
    exc_info: bool = False,
) -> logging.LogRecord:
    """Create a minimal LogRecord for formatter tests."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if ctx is not None:
        record.ctx = ctx  # type: ignore[attr-defined]
    if exc_info:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record.exc_info = sys.exc_info()
    return record


# ---------------------------------------------------------------------------
# JsonLineFormatter
# ---------------------------------------------------------------------------


class TestJsonLineFormatter:
    def setup_method(self) -> None:
        self.fmt = JsonLineFormatter()

    def test_format_basic_record(self) -> None:
        record = _make_record("Locked volume E:")
        line = self.fmt.format(record)
        obj = json.loads(line)
        assert obj["lvl"] == "INFO"
        assert obj["mod"] == "diskwriter"
        assert obj["msg"] == "Locked volume E:"
        assert "ctx" not in obj
        assert "exc" not in obj

    def test_timestamp_format(self) -> None:
        """ts must be UTC ISO 8601 with ms precision ending in Z."""
        record = _make_record()
        line = self.fmt.format(record)
        ts = json.loads(line)["ts"]
        # Matches: 2026-05-29T02:15:01.234Z
        import re

        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts), ts

    def test_format_with_ctx(self) -> None:
        ctx = {"phys_drive": 2, "volume": "E:"}
        record = _make_record("Locked volume E:", ctx=ctx)
        line = self.fmt.format(record)
        obj = json.loads(line)
        assert obj["ctx"] == {"phys_drive": 2, "volume": "E:"}

    def test_format_with_exc_info(self) -> None:
        record = _make_record("Something broke", exc_info=True)
        line = self.fmt.format(record)
        obj = json.loads(line)
        assert "exc" in obj
        # exc is a list of traceback strings
        exc_text = "".join(obj["exc"])
        assert "ValueError" in exc_text
        assert "boom" in exc_text

    def test_format_error_level(self) -> None:
        record = _make_record("WriteFile failed", level=logging.ERROR)
        line = self.fmt.format(record)
        assert json.loads(line)["lvl"] == "ERROR"

    def test_format_returns_valid_json(self) -> None:
        record = _make_record("test é unicode")
        line = self.fmt.format(record)
        obj = json.loads(line)  # must not raise
        assert obj["msg"] == "test é unicode"

    def test_no_ctx_key_when_ctx_none(self) -> None:
        record = _make_record("msg")
        line = self.fmt.format(record)
        assert "ctx" not in json.loads(line)


# ---------------------------------------------------------------------------
# LogRotationManager
# ---------------------------------------------------------------------------


class TestLogRotationManager:
    def test_open_session_log_creates_file(self, tmp_path: Path) -> None:
        mgr = LogRotationManager(tmp_path)
        p = mgr.open_session_log(session_id="2026-01-01T00-00-00.000Z")
        assert p.exists()
        assert p.name == "flash-2026-01-01T00-00-00.000Z.log"

    def test_open_session_log_creates_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "subdir" / "logs"
        mgr = LogRotationManager(log_dir)
        p = mgr.open_session_log(session_id="test")
        assert log_dir.exists()
        assert p.exists()

    def test_rotation_deletes_oldest_when_max_exceeded(self, tmp_path: Path) -> None:
        """Creating the (max_files+1)-th file must delete the oldest."""
        mgr = LogRotationManager(tmp_path, max_files=5)
        created: list[Path] = []
        for i in range(5):
            # Nudge mtime so glob sort is deterministic
            time.sleep(0.01)
            p = mgr.open_session_log(session_id=f"2026-01-0{i + 1}T00-00-00.000Z")
            created.append(p)

        # Now add a 6th — should delete the first
        time.sleep(0.01)
        mgr.open_session_log(session_id="2026-01-06T00-00-00.000Z")

        remaining = list(tmp_path.glob("flash-*.log"))
        assert len(remaining) == 5
        # The oldest (first created) must be gone
        assert not created[0].exists()

    def test_rotation_keeps_exactly_max_files(self, tmp_path: Path) -> None:
        """After N > max_files opens, exactly max_files files remain."""
        max_files = 3
        mgr = LogRotationManager(tmp_path, max_files=max_files)
        for i in range(7):
            time.sleep(0.01)
            mgr.open_session_log(session_id=f"session-{i:02d}")
        remaining = list(tmp_path.glob("flash-*.log"))
        assert len(remaining) == max_files

    def test_no_rotation_when_under_limit(self, tmp_path: Path) -> None:
        """Files are not deleted until max_files is reached."""
        mgr = LogRotationManager(tmp_path, max_files=20)
        for i in range(5):
            mgr.open_session_log(session_id=f"s-{i}")
        assert len(list(tmp_path.glob("flash-*.log"))) == 5

    def test_auto_timestamp_used_when_session_id_none(self, tmp_path: Path) -> None:
        mgr = LogRotationManager(tmp_path)
        p = mgr.open_session_log()
        assert p.name.startswith("flash-")
        assert p.suffix == ".log"
        assert p.exists()
