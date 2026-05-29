"""Tests for DriveListModel — QAbstractListModel wrapping enumerate_removable_drives."""
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def test_model_reports_drive_count(qtbot, fake_platform_io):
    from astromechos_imager.ui.drive_list_model import DriveListModel
    # Use small sizes to avoid exhausting temp-partition disk space on Windows
    fake_platform_io.add_drive(2, size=1024 * 1024)
    fake_platform_io.add_drive(3, size=1024 * 1024)
    m = DriveListModel(fake_platform_io)
    assert m.rowCount() == 2


def test_model_exposes_size_human(qtbot, fake_platform_io):
    from astromechos_imager.ui.drive_list_model import DriveListModel
    from PySide6.QtCore import Qt
    # Use a small physical file but verify the human() helper works for MB range
    fake_platform_io.add_drive(2, size=4 * 1024 * 1024)
    m = DriveListModel(fake_platform_io)
    idx = m.index(0, 0)
    size_human = m.data(idx, Qt.UserRole + 4)
    # 4 MB -> "4.0 MB"
    assert "MB" in size_human


def test_model_refresh_picks_up_new_drive(qtbot, fake_platform_io):
    from astromechos_imager.ui.drive_list_model import DriveListModel
    m = DriveListModel(fake_platform_io)
    assert m.rowCount() == 0
    fake_platform_io.add_drive(2, size=1024 * 1024)
    m.refresh()
    assert m.rowCount() == 1


def test_driveIdAt_returns_correct_id(qtbot, fake_platform_io):
    from astromechos_imager.ui.drive_list_model import DriveListModel
    fake_platform_io.add_drive(7, size=1024 * 1024)
    m = DriveListModel(fake_platform_io)
    assert m.driveIdAt(0) == 7
    assert m.driveIdAt(99) == -1


def test_human_size_helper_gb():
    """Unit test _human() directly without needing a physical file."""
    from astromechos_imager.ui.drive_list_model import _human
    result = _human(32 * 1024 * 1024 * 1024)
    assert "GB" in result

    result_mb = _human(4 * 1024 * 1024)
    assert "MB" in result_mb
