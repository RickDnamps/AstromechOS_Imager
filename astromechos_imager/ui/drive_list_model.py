"""Drive list model exposed to QML for the Storage step."""
from __future__ import annotations

import logging

from PySide6.QtCore import (
    QAbstractListModel, QByteArray, QModelIndex, Property, Qt, QTimer, Signal,
    Slot,
)

from astromechos_imager.core.models import DiskRef
from astromechos_imager.core.platform_io import PlatformIO


_log = logging.getLogger(__name__)


_ROLE_NAMES = {
    Qt.UserRole + 0: b"physicalDriveId",
    Qt.UserRole + 1: b"devicePath",
    Qt.UserRole + 2: b"driveLetters",      # comma-joined
    Qt.UserRole + 3: b"sizeBytes",
    Qt.UserRole + 4: b"sizeHuman",
    Qt.UserRole + 5: b"model",
    Qt.UserRole + 6: b"serial",
}


def _human_size(size_bytes: int) -> str:
    """Render a byte count as a human-friendly string (kept module-level so
    QML Property getters and the per-row ``sizeHuman`` role share the
    exact same formatting)."""
    n = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# Backwards-compatible alias — older code (or tests) may reference _human().
_human = _human_size


def _drive_letters_str(d: DiskRef) -> str:
    """Match the ``driveLetters`` role formatting used by ``data()``."""
    return ", ".join(d.drive_letters) + ":" if d.drive_letters else ""


class DriveListModel(QAbstractListModel):
    """Refreshes every 2 s. PlatformIO injected so tests can use FakePlatformIO.

    System drive exclusion is enforced at the enumerate_removable_drives() layer
    in astromechos_imager/platform/windows.py (Phase 4.2). The system drive never
    appears in this model, so QML does not need to disable or filter any rows.

    Exposes ``count`` + ``firstDrive*`` Qt Properties so QML can bind directly
    instead of relying on a hidden ListView delegate (Qt 6 does not instantiate
    a delegate when ``width=0``/``height=0``/``visible=false`` — the delegate's
    ``Component.onCompleted`` never fires and properties stay at their defaults).
    """
    countChanged = Signal()
    firstDriveChanged = Signal()

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
        old_first = before[0] if before else (None, None)
        new_first = after[0] if after else (None, None)
        if before != after:
            self.beginResetModel()
            self._drives = new
            self.endResetModel()
            self.countChanged.emit()
            _log.info("DriveListModel refreshed: %d drive(s)", len(new))
            for i, d in enumerate(new):
                _log.info(
                    "  drive[%d] phys_id=%d letters=%s size=%d model=%s",
                    i, d.physical_drive_id, _drive_letters_str(d) or "(none)",
                    d.size_bytes, d.model,
                )
        if old_first != new_first:
            self.firstDriveChanged.emit()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._drives)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._drives)):
            return None
        d = self._drives[index.row()]
        if role == Qt.UserRole + 0: return d.physical_drive_id
        if role == Qt.UserRole + 1: return d.device_path
        if role == Qt.UserRole + 2: return _drive_letters_str(d)
        if role == Qt.UserRole + 3: return int(d.size_bytes)
        if role == Qt.UserRole + 4: return _human_size(d.size_bytes)
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

    # ── QML-facing Properties (direct binding source for Step4Role) ──────

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._drives)

    @Property(int, notify=firstDriveChanged)
    def firstDriveId(self) -> int:
        return self._drives[0].physical_drive_id if self._drives else -1

    @Property(str, notify=firstDriveChanged)
    def firstDriveLetters(self) -> str:
        if not self._drives:
            return ""
        return _drive_letters_str(self._drives[0])

    @Property(str, notify=firstDriveChanged)
    def firstDriveModel(self) -> str:
        return self._drives[0].model if self._drives else ""

    @Property(str, notify=firstDriveChanged)
    def firstDriveSize(self) -> str:
        return _human_size(self._drives[0].size_bytes) if self._drives else ""
