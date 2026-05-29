"""Wizard navigation state — a QObject exposed to QML as `wizardState`."""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot


class WizardState(QObject):
    """Tracks the current wizard step (1–6) and exposes navigation slots.

    Steps:
        1 — Mode (flash both / master only / slave only)
        2 — Images (browse source .img/.xz/.gz/.zip per role)
        3 — Storage (pick target SD card per role)
        4 — Customize (authorized_keys + advanced)
        5 — Confirm & Flash (summary, big red WRITE button, progress)
        6 — Done (recap + next steps)
    """
    currentStepChanged = Signal(int)

    MIN_STEP = 1
    MAX_STEP = 6

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._step = self.MIN_STEP

    @Property(int, notify=currentStepChanged)
    def currentStep(self) -> int:
        return self._step

    @Slot()
    def next(self) -> None:
        """Advance one step, clamped at MAX_STEP."""
        if self._step < self.MAX_STEP:
            self._step += 1
            self.currentStepChanged.emit(self._step)

    @Slot()
    def back(self) -> None:
        """Step back one, clamped at MIN_STEP."""
        if self._step > self.MIN_STEP:
            self._step -= 1
            self.currentStepChanged.emit(self._step)

    @Slot(int)
    def goto(self, step: int) -> None:
        """Jump directly to a specific step (no-op if already there or out of range)."""
        if self.MIN_STEP <= step <= self.MAX_STEP and step != self._step:
            self._step = step
            self.currentStepChanged.emit(self._step)
