"""Drive list model exposed to QML for the Storage step."""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel, QByteArray, QModelIndex, Qt, QTimer, Signal, Slot,
)

from astromechos_imager.core.models import DiskRef
from astromechos_imager.core.platform_io import PlatformIO


_ROLE_NAMES = {
    Qt.UserRole + 0: b"physicalDriveId",
    Qt.UserRole + 1: b"devicePath",
    Qt.UserRole + 2: b"driveLetters",      # comma-joined
    Qt.UserRole + 3: b"sizeBytes",
    Qt.UserRole + 4: b"sizeHuman",
    Qt.UserRole + 5: b"model",
    Qt.UserRole + 6: b"serial",
}


def _human(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}" if unit == "B" else f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


class DriveListModel(QAbstractListModel):
    """Refreshes every 2 s. PlatformIO injected so tests can use FakePlatformIO.

    System drive exclusion is enforced at the enumerate_removable_drives() layer
    in astromechos_imager/platform/windows.py (Phase 4.2). The system drive never
    appears in this model, so QML does not need to disable or filter any rows.
    """
    countChanged = Signal()

    def __init__(self, platform_io: PlatformIO, parent=None) -> None:
        super().__init__(parent)
        self._platform = platform_io
        self._drives: list[DiskRef] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        # Initial population + start the 2 s poll
        self.refresh()

    def start_polling(self) -> None:
        if not self._timer.isActive():
            self._timer.start(2000)

    def stop_polling(self) -> None:
        self._timer.stop()

    @Slot()
    def refresh(self) -> None:
        new = list(self._platform.enumerate_removable_drives())
        # Only reset if changed (cheap diff by phys_id+size)
        before = [(d.physical_drive_id, d.size_bytes) for d in self._drives]
        after = [(d.physical_drive_id, d.size_bytes) for d in new]
        if before != after:
            self.beginResetModel()
            self._drives = new
            self.endResetModel()
            self.countChanged.emit()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._drives)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._drives)):
            return None
        d = self._drives[index.row()]
        if role == Qt.UserRole + 0: return d.physical_drive_id
        if role == Qt.UserRole + 1: return d.device_path
        if role == Qt.UserRole + 2: return ", ".join(d.drive_letters) + ":" if d.drive_letters else ""
        if role == Qt.UserRole + 3: return int(d.size_bytes)
        if role == Qt.UserRole + 4: return _human(d.size_bytes)
        if role == Qt.UserRole + 5: return d.model
        if role == Qt.UserRole + 6: return d.serial
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {k: QByteArray(v) for k, v in _ROLE_NAMES.items()}

    @Slot(int, result=int)
    def driveIdAt(self, row: int) -> int:
        if 0 <= row < len(self._drives):
            return self._drives[row].physical_drive_id
        return -1
