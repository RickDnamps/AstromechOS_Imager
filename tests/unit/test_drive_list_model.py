"""Tests for DriveListModel's QML-facing Properties + refresh logging.

These cover the regression that broke Step 4 ("SD card not detected"):
the old hidden ``ListView { width:0; height:0; visible:false }`` pattern
in Step4Role.qml never instantiated its delegate in Qt 6, so the
``firstDrive*`` properties stayed at -1 / "". DriveListModel now exposes
those values as Qt Properties so QML can bind directly.
"""
from __future__ import annotations

import logging
import sys

import pytest

# Ensure a QGuiApplication exists for QAbstractListModel signal machinery
# in headless test runs (CI uses QT_QPA_PLATFORM=offscreen).
from PySide6.QtCore import QCoreApplication

from astromechos_imager.core.models import DiskRef
from astromechos_imager.ui.drive_list_model import DriveListModel


@pytest.fixture(scope="module", autouse=True)
def _qcoreapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv or ["test"])
    yield app


class _StubPlatform:
    """Minimal PlatformIO stub — only enumerate_removable_drives is used."""

    def __init__(self, drives: list[DiskRef] | None = None):
        self.drives = list(drives) if drives else []

    def enumerate_removable_drives(self):
        return list(self.drives)

    # Unused by DriveListModel but required by the Protocol shape
    def lock_and_dismount(self, letters, physical_drive_id=None):
        return []

    def open_raw_device(self, phys_id):
        raise NotImplementedError

    def close_handle(self, h):
        pass


def _disk(phys_id: int, size: int = 32 << 30,
          model: str = "Test SD", letters: tuple[str, ...] = ("E",)) -> DiskRef:
    return DiskRef(
        physical_drive_id=phys_id,
        device_path=f"\\\\.\\PHYSICALDRIVE{phys_id}",
        drive_letters=letters,
        size_bytes=size,
        model=model,
        serial=f"SN-{phys_id}",
    )


def test_firstDriveId_empty_returns_minus_one():
    model = DriveListModel(_StubPlatform([]))
    assert model.firstDriveId == -1
    assert model.firstDriveLetters == ""
    assert model.firstDriveModel == ""
    assert model.firstDriveSize == ""
    assert model.count == 0


def test_firstDriveId_populated_returns_phys_id():
    platform = _StubPlatform([_disk(3, size=32_000_000_000, model="SanDisk Ultra")])
    model = DriveListModel(platform)
    assert model.firstDriveId == 3
    assert model.firstDriveLetters == "E:"
    assert model.firstDriveModel == "SanDisk Ultra"
    # Size string formatted as "29.8 GB" — verify it's non-empty + contains GB.
    assert "GB" in model.firstDriveSize


def test_firstDriveChanged_emits_on_refresh_when_first_drive_changes():
    platform = _StubPlatform([_disk(2)])
    model = DriveListModel(platform)
    emissions: list[int] = []
    model.firstDriveChanged.connect(lambda: emissions.append(model.firstDriveId))
    # Swap the first drive
    platform.drives = [_disk(7, size=64 << 30, model="Kingston")]
    model.refresh()
    assert emissions == [7]
    assert model.firstDriveId == 7


def test_firstDriveChanged_does_not_emit_when_unchanged():
    platform = _StubPlatform([_disk(2)])
    model = DriveListModel(platform)
    emissions: list[int] = []
    model.firstDriveChanged.connect(lambda: emissions.append(1))
    # Same drives → no signal
    model.refresh()
    model.refresh()
    assert emissions == []


def test_count_property_matches_rowCount():
    platform = _StubPlatform([_disk(2), _disk(3)])
    model = DriveListModel(platform)
    assert model.count == 2
    assert model.count == model.rowCount()
    platform.drives = []
    model.refresh()
    assert model.count == 0
    assert model.count == model.rowCount()


def test_refresh_logs_drive_summary(caplog):
    """When the model resets, INFO log lines describe each accepted drive."""
    platform = _StubPlatform([_disk(2, size=32_000_000_000, model="SanDisk Ultra")])
    with caplog.at_level(logging.INFO,
                         logger="astromechos_imager.ui.drive_list_model"):
        # Construction triggers a refresh (logs N drives)
        DriveListModel(platform)
    messages = "\n".join(rec.message for rec in caplog.records)
    assert "DriveListModel refreshed: 1 drive(s)" in messages
    assert "phys_id=2" in messages
    assert "SanDisk Ultra" in messages


# ── ID → field lookups (Step 5 friendly label rendering) ──────────────


def test_lettersForDriveId_returns_letter_for_present_drive():
    platform = _StubPlatform([_disk(7, letters=("K",))])
    model = DriveListModel(platform)
    assert model.lettersForDriveId(7) == "K:"


def test_lettersForDriveId_returns_empty_for_missing_drive():
    platform = _StubPlatform([_disk(7, letters=("K",))])
    model = DriveListModel(platform)
    assert model.lettersForDriveId(99) == ""


def test_modelForDriveId_returns_model_for_present_drive():
    platform = _StubPlatform([_disk(7, model="SanDisk Ultra")])
    model = DriveListModel(platform)
    assert model.modelForDriveId(7) == "SanDisk Ultra"
    assert model.modelForDriveId(99) == ""


def test_sizeForDriveId_uses_human_format():
    """62528578560 bytes → '58.2 GB' from _human_size."""
    platform = _StubPlatform([_disk(7, size=62528578560)])
    model = DriveListModel(platform)
    assert model.sizeForDriveId(7) == "58.2 GB"
    assert model.sizeForDriveId(99) == ""


def test_labelForDriveId_present_drive_format():
    """Combined label: '<letter>: <model> <size>'."""
    platform = _StubPlatform([
        _disk(7, letters=("K",), model="SanDisk Ultra", size=62528578560),
    ])
    model = DriveListModel(platform)
    assert model.labelForDriveId(7) == "K: SanDisk Ultra 58.2 GB"


def test_labelForDriveId_missing_drive_shows_unplugged_hint():
    """Drive id no longer in the live model → 'drive N (unplugged?)'."""
    platform = _StubPlatform([_disk(7, letters=("K",))])
    model = DriveListModel(platform)
    # Operator picked drive 7, then unplugged it — only 7 is live; query 99.
    assert model.labelForDriveId(99) == "drive 99 (unplugged?)"
    # And empty model
    empty = DriveListModel(_StubPlatform([]))
    assert empty.labelForDriveId(42) == "drive 42 (unplugged?)"
