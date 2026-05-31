"""Unit tests for the JSONL logger wiring in astromechos_imager.ui.app.

Locks in subtask 1 of the logging-migration fix: ``main()`` MUST invoke
``setup_logging()`` exactly once before ``build_app()`` runs, so the
%APPDATA%\\AstromechOS Imager\\logs\\flash-*.log session file is created
and the root logger picks up records emitted by the migrated stderr
sinks (DriveListModel bring-up, WizardState role check, bootpartition
cleanup).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from astromechos_imager.ui import app


class TestMainWiresSetupLogging:
    def test_main_invokes_setup_logging_exactly_once(self) -> None:
        """``main()`` MUST call ``setup_logging()`` once before ``build_app()``."""
        fake_app = MagicMock()
        fake_app.exec.return_value = 0
        fake_engine = MagicMock()
        fake_state = MagicMock()

        with patch.object(app, "setup_logging") as mock_setup, patch.object(
            app, "build_app", return_value=(fake_app, fake_engine, fake_state)
        ):
            rc = app.main()

        assert mock_setup.call_count == 1, (
            f"setup_logging should be called exactly once; got "
            f"{mock_setup.call_count}"
        )
        # main() must still return the QApplication exec rc
        assert rc == 0
        fake_app.exec.assert_called_once()

    def test_main_continues_when_setup_logging_raises(self) -> None:
        """A setup_logging crash must not prevent app launch.

        The frozen stderr safety net at app.py:22-30 captures anything that
        escapes, so main() should still call build_app() and return its rc.
        """
        fake_app = MagicMock()
        fake_app.exec.return_value = 0
        fake_engine = MagicMock()
        fake_state = MagicMock()

        with patch.object(
            app, "setup_logging", side_effect=OSError("disk full")
        ) as mock_setup, patch.object(
            app, "build_app", return_value=(fake_app, fake_engine, fake_state)
        ) as mock_build:
            rc = app.main()

        assert mock_setup.call_count == 1
        mock_build.assert_called_once()
        assert rc == 0
