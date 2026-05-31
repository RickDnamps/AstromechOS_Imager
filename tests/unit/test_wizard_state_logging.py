"""Unit tests for the role-check error-path logging in WizardState.

Locks in subtask 2 of the logging-migration fix: when ``validate_image_role``
raises an unexpected exception (pyfatfs ImportError, transient I/O, etc.),
the daemon thread inside ``_kick_role_check`` MUST route the traceback
through the standard ``logging`` module so it lands in the JSONL session
log — not just on a possibly-redirected stderr.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

# PySide6 must be importable for QObject-based WizardState to instantiate.
PySide6 = pytest.importorskip("PySide6")

from astromechos_imager.ui.wizard_state import WizardState  # noqa: E402


def _wait_for(predicate, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` until it returns truthy or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class TestRoleCheckLogsToLogger:
    def test_unexpected_exception_emits_error_log_record(
        self,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A synthetic RuntimeError from validate_image_role must land in caplog.

        Before the migration, the bare-Exception branch only wrote to
        ``sys.stderr``, which pytest does NOT capture as a log record. The
        test fails on the un-migrated code and passes after the
        ``logging.getLogger(__name__).exception(...)`` wiring.
        """
        # The daemon emits a Qt signal on completion — we use that as a
        # synchronisation barrier instead of an arbitrary sleep.
        state = WizardState()

        # _kick_role_check requires a real on-disk file before it dispatches
        # the worker thread (otherwise it short-circuits to "none").
        img = tmp_path / "synthetic-master.img"
        img.write_bytes(b"not a real image, only here to satisfy is_file()")

        # Patch validate_image_role at the module that the inner closure
        # imports it from. The inner closure does
        # ``from astromechos_imager.core.image_validator import validate_image_role``
        # at call time, so we monkeypatch the SOURCE attribute — that's
        # what the closure-time import will resolve to.
        from astromechos_imager.core import image_validator as iv

        def _boom(*_a, **_kw):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(iv, "validate_image_role", _boom)

        with caplog.at_level(logging.ERROR, logger="astromechos_imager.ui.wizard_state"):
            state._kick_role_check("master", str(img))

            # Wait for the daemon's worker thread to finish. We use the
            # appearance of an ERROR record from the migrated branch as the
            # synchronisation barrier — without a running Qt event loop the
            # queued ``_roleStatusUpdated`` signal would never deliver, so
            # checking the log records directly is the only reliable
            # cross-thread signal.
            got_log = _wait_for(
                lambda: any(
                    r.levelno == logging.ERROR
                    and r.name == "astromechos_imager.ui.wizard_state"
                    for r in caplog.records
                )
            )

        assert got_log, (
            "Daemon thread never emitted an ERROR log record; "
            f"records={[(r.name, r.levelname) for r in caplog.records]}"
        )

        # The migrated code path calls
        #   logging.getLogger(__name__).exception("role check failed for %s", name)
        # so we should see at least one ERROR record on that logger
        # mentioning the filename, with exc_info populated.
        matching = [
            r
            for r in caplog.records
            if r.levelno == logging.ERROR
            and r.name == "astromechos_imager.ui.wizard_state"
            and img.name in r.getMessage()
        ]
        assert matching, (
            "No ERROR log record found for the role-check failure. "
            f"All captured records: {[(r.name, r.levelname, r.getMessage()) for r in caplog.records]}"
        )
        # ``logger.exception`` MUST attach traceback info so the JSONL
        # formatter can serialise it.
        assert matching[0].exc_info is not None, (
            "logger.exception() should attach exc_info; got None"
        )
