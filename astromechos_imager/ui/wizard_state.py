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
    modeChanged = Signal(str)
    masterImagePathChanged = Signal(str)
    slaveImagePathChanged = Signal(str)

    MIN_STEP = 1
    MAX_STEP = 6

    MODE_BOTH = "both"
    MODE_MASTER_ONLY = "master_only"
    MODE_SLAVE_ONLY = "slave_only"
    VALID_MODES = (MODE_BOTH, MODE_MASTER_ONLY, MODE_SLAVE_ONLY)

    SUPPORTED_IMAGE_EXTENSIONS = (".img", ".xz", ".gz", ".zip")  # .img.xz, .img.gz handled by stem-check

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._step = self.MIN_STEP
        self._mode = self.MODE_BOTH  # default = recommended
        self._master_image_path = ""
        self._slave_image_path = ""

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

    # ------------------------------------------------------------------
    # Step 1 — Mode
    # ------------------------------------------------------------------

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode

    @Slot(str)
    def setMode(self, mode: str) -> None:
        if mode in self.VALID_MODES and mode != self._mode:
            self._mode = mode
            self.modeChanged.emit(self._mode)

    # ------------------------------------------------------------------
    # Step 2 — Image paths
    # ------------------------------------------------------------------

    @Property(str, notify=masterImagePathChanged)
    def masterImagePath(self) -> str:
        return self._master_image_path

    @Property(str, notify=slaveImagePathChanged)
    def slaveImagePath(self) -> str:
        return self._slave_image_path

    @Slot(str)
    def setMasterImagePath(self, p: str) -> None:
        p = self._normalize_path(p)
        if p != self._master_image_path:
            self._master_image_path = p
            self.masterImagePathChanged.emit(p)

    @Slot(str)
    def setSlaveImagePath(self, p: str) -> None:
        p = self._normalize_path(p)
        if p != self._slave_image_path:
            self._slave_image_path = p
            self.slaveImagePathChanged.emit(p)

    @staticmethod
    def _normalize_path(p: str) -> str:
        """Strip file:// scheme and decode."""
        from urllib.parse import urlparse, unquote
        if p.startswith("file://"):
            u = urlparse(p)
            # Handle Windows file:///J:/foo and file:///J:\foo cases
            return unquote(u.path.lstrip("/")) if u.path else ""
        return p

    @Slot(str, result=bool)
    def isValidImagePath(self, p: str) -> bool:
        """True if path exists AND has a supported extension."""
        from pathlib import Path
        if not p:
            return False
        norm = self._normalize_path(p)
        fp = Path(norm)
        if not fp.is_file():
            return False
        suffixes = [s.lower() for s in fp.suffixes[-2:]]
        return any(s in self.SUPPORTED_IMAGE_EXTENSIONS for s in suffixes)
