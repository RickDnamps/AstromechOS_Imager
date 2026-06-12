"""Live system-state surface for QML (notify-capable, unlike a static
context property).

Currently carries one fact: whether the automount defense is armed. The
session guard arms it on a background thread (audit defect A6 - the old
synchronous pre-Qt mountvol calls could stall the window for the full
subprocess timeouts), so the QML banner needs a property that can CHANGE
after engine load. Signal emission from the arming thread is safe: Qt
queues the notification to the main thread.
"""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal


class SystemStatus(QObject):
    automountDefenseActiveChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Optimistic default: don't flash the warning banner during the
        # sub-second arming window; flip to False only on a confirmed
        # mountvol /N failure.
        self._automount_defense_active = True

    @Property(bool, notify=automountDefenseActiveChanged)
    def automountDefenseActive(self) -> bool:
        return self._automount_defense_active

    def setAutomountDefenseActive(self, value: bool) -> None:
        value = bool(value)
        if value != self._automount_defense_active:
            self._automount_defense_active = value
            self.automountDefenseActiveChanged.emit()
