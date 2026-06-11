"""WP1 — the win32 boundary tells the truth about mountvol.

Pins the contract that made the anti-popup defense a fiction when broken:
``_run_mountvol`` must return True ONLY on exit code 0, ``disable_automount``
must not drop the marker on failure, and ``enable_automount`` must KEEP the
marker when /E fails (a failed restore must stay repairable).

All subprocess calls are mocked — these tests never touch the real Mount
Manager, regardless of the machine they run on.
"""
from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

if sys.platform != "win32":  # pragma: no cover - module is win32-only
    pytest.skip("windows platform module", allow_module_level=True)

from astromechos_imager.platform import windows as W


@pytest.fixture()
def marker(tmp_path, monkeypatch):
    """Redirect the automount marker into tmp_path."""
    path = tmp_path / "automount_disabled.marker"
    monkeypatch.setattr(W, "_automount_marker_path", lambda: path)
    return path


def _mock_mountvol(monkeypatch, returncode, stderr=b""):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=returncode, stdout=b"", stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_run_mountvol_true_only_on_rc_zero(monkeypatch):
    _mock_mountvol(monkeypatch, 0)
    assert W._run_mountvol("/N") is True


def test_run_mountvol_false_on_nonzero_rc(monkeypatch, caplog):
    _mock_mountvol(monkeypatch, 1, stderr=b"Access is denied.")
    with caplog.at_level("WARNING"):
        assert W._run_mountvol("/N") is False
    assert "Access is denied" in caplog.text


def test_run_mountvol_false_on_spawn_failure(monkeypatch):
    def boom(argv, **kwargs):
        raise FileNotFoundError("mountvol")

    monkeypatch.setattr(subprocess, "run", boom)
    assert W._run_mountvol("/N") is False


def test_disable_automount_failure_writes_no_marker(monkeypatch, marker):
    _mock_mountvol(monkeypatch, 1)
    assert W.disable_automount() is False
    assert not marker.exists()


def test_disable_automount_success_writes_marker(monkeypatch, marker):
    _mock_mountvol(monkeypatch, 0)
    assert W.disable_automount() is True
    assert marker.exists()


def test_enable_automount_failure_keeps_marker(monkeypatch, marker):
    marker.write_text("disabled\n", encoding="ascii")
    _mock_mountvol(monkeypatch, 1)
    assert W.enable_automount() is False
    assert marker.exists(), "a failed /E must keep the repair record"


def test_enable_automount_success_clears_marker(monkeypatch, marker):
    marker.write_text("disabled\n", encoding="ascii")
    _mock_mountvol(monkeypatch, 0)
    assert W.enable_automount() is True
    assert not marker.exists()


def test_restore_if_crashed_failed_restore_keeps_marker(monkeypatch, marker):
    marker.write_text("disabled\n", encoding="ascii")
    _mock_mountvol(monkeypatch, 1)
    W.restore_automount_if_crashed()
    assert marker.exists()


def test_restore_if_crashed_noop_without_marker(monkeypatch, marker):
    calls = _mock_mountvol(monkeypatch, 0)
    W.restore_automount_if_crashed()
    assert calls == []
