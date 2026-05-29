"""Bridges PairFlashJob / FlashJob to QML. Runs the job in a QThread."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Property, Signal, Slot

from astromechos_imager.core.diskwriter import DiskWriterProgress
from astromechos_imager.core.models import Role


class _FlashWorker(QObject):
    """Lives in a QThread; runs job.run() then emits 'finished'."""
    progressMaster = Signal(float, str)   # fraction, phase
    progressSlave = Signal(float, str)
    finished = Signal(bool, str)          # ok, error_msg
    phaseChanged = Signal(str, str)       # role_value, phase_str

    def __init__(self, job, is_pair: bool):
        super().__init__()
        self._job = job
        self._is_pair = is_pair

    @Slot()
    def run(self) -> None:
        try:
            if self._is_pair:
                self._job.on_progress = self._on_pair_progress
            else:
                self._job.on_progress = self._on_single_progress
            result = self._job.run()
            if self._is_pair:
                ok = result.master.ok and result.slave.ok
                err = "" if ok else (
                    str(result.master.error or "")
                    + (("; " + str(result.slave.error)) if result.slave.error else "")
                )
            else:
                ok = bool(result.ok)
                err = "" if ok else str(getattr(result, "error", "")) or "flash failed"
            self.finished.emit(ok, err)
        except Exception as e:
            self.finished.emit(False, f"{type(e).__name__}: {e}")

    def _on_pair_progress(self, role: Role, p: DiskWriterProgress) -> None:
        frac = (p.bytes_done / p.bytes_total) if p.bytes_total else 0.0
        if role is Role.MASTER:
            self.progressMaster.emit(frac, p.phase)
        else:
            self.progressSlave.emit(frac, p.phase)

    def _on_single_progress(self, p: DiskWriterProgress) -> None:
        frac = (p.bytes_done / p.bytes_total) if p.bytes_total else 0.0
        self.progressMaster.emit(frac, p.phase)


class FlashViewModel(QObject):
    """Top-level controller for the flash step. Owns the QThread + worker."""
    statusChanged = Signal()
    masterProgressChanged = Signal()
    masterPhaseChanged = Signal()
    slaveProgressChanged = Signal()
    slavePhaseChanged = Signal()
    errorMessageChanged = Signal()

    def __init__(self, wizard_state, parent=None):
        super().__init__(parent)
        self._wizard_state = wizard_state
        self._status = "idle"               # idle | flashing | done | error
        self._master_progress = 0.0
        self._master_phase = ""
        self._slave_progress = 0.0
        self._slave_phase = ""
        self._error_message = ""
        self._thread: QThread | None = None
        self._worker: _FlashWorker | None = None
        self._cancel_event = threading.Event()

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(float, notify=masterProgressChanged)
    def masterProgress(self) -> float:
        return self._master_progress

    @Property(str, notify=masterPhaseChanged)
    def masterPhase(self) -> str:
        return self._master_phase

    @Property(float, notify=slaveProgressChanged)
    def slaveProgress(self) -> float:
        return self._slave_progress

    @Property(str, notify=slavePhaseChanged)
    def slavePhase(self) -> str:
        return self._slave_phase

    @Property(str, notify=errorMessageChanged)
    def errorMessage(self) -> str:
        return self._error_message

    @Slot(QObject)
    def startWithJob(self, job_obj) -> None:
        """job_obj should be a Python object exposing the PairFlashJob / FlashJob
        interface. In tests we pass FakeJob; in production app.build_app() wires
        a real factory that constructs from wizardState."""
        if self._status == "flashing":
            return
        self._cancel_event.clear()
        self._status = "flashing"
        self.statusChanged.emit()
        is_pair = hasattr(job_obj, "master_target")
        self._thread = QThread()
        self._worker = _FlashWorker(job_obj, is_pair)
        self._worker.moveToThread(self._thread)
        self._worker.progressMaster.connect(self._update_master)
        self._worker.progressSlave.connect(self._update_slave)
        self._worker.finished.connect(self._on_finished)
        self._thread.started.connect(self._worker.run)
        self._thread.start()

    @Slot()
    def startFromWizard(self) -> None:
        """Build the PairFlashJob/FlashJob from wizardState + platform IO, then start.
        On dev hosts without real SD cards this will fail at lock_and_dismount —
        that's the operator's signal to plug a card in."""
        job = _build_flash_job(self._wizard_state)
        if job is not None:
            self.startWithJob(job)

    @Slot()
    def cancel(self) -> None:
        self._cancel_event.set()
        if self._worker is not None and hasattr(self._worker._job, "cancel_event"):
            self._worker._job.cancel_event.set()

    def _update_master(self, frac, phase):
        self._master_progress = frac
        self._master_phase = phase
        self.masterProgressChanged.emit()
        self.masterPhaseChanged.emit()

    def _update_slave(self, frac, phase):
        self._slave_progress = frac
        self._slave_phase = phase
        self.slaveProgressChanged.emit()
        self.slavePhaseChanged.emit()

    def _on_finished(self, ok, err):
        self._status = "done" if ok else "error"
        self._error_message = err
        self.statusChanged.emit()
        self.errorMessageChanged.emit()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(500)
            self._thread = None
            self._worker = None


def _build_flash_job(wizard_state, platform_io=None):
    """Build a PairFlashJob or FlashJob from wizard_state fields.

    Returns None and logs a warning if construction fails (e.g. no real drives).
    This function is module-level so it can be unit-tested with a fake wizard_state.
    """
    try:
        import sys
        if platform_io is None:
            if sys.platform == "win32":
                from astromechos_imager.platform.windows import WindowsPlatformIO
                platform_io = WindowsPlatformIO()
            else:
                return None

        from astromechos_imager.core.imagesource import open_image
        from astromechos_imager.core.models import (
            FirstbootConfig, Role, DiskRef,
        )
        from astromechos_imager.core.orchestrator import FlashJob, PairFlashJob
        from astromechos_imager.core.keygen import (
            generate_ed25519, generate_hotspot_bootstrap, generate_linux_account,
            load_persisted_pair, save_persisted_pair,
        )

        # Zero-Touch: no user-pasted keys, ever. The Master↔Slave pair is
        # auto-generated and persisted in %APPDATA% — reusing the same pair
        # across runs lets the operator re-flash the Master alone without
        # invalidating the existing Slave's authorized_keys.
        existing = load_persisted_pair()
        ed25519 = existing if existing is not None else generate_ed25519()
        if existing is None:
            # First run — persist the freshly-generated pair so future flashes
            # (master_only, slave_only) reuse the same keys and keep the pair
            # symmetric across cards.
            save_persisted_pair(ed25519)
        hotspot = generate_hotspot_bootstrap()
        linux_account = generate_linux_account()

        firstboot = FirstbootConfig(
            authorized_keys=[],   # zero-touch: no operator keys injected
            hostname_master=wizard_state.hostnameMaster,
            hostname_slave=wizard_state.hostnameSlave,
            install_user=linux_account.username,
            ed25519_pair=ed25519,
            hotspot=hotspot,
            repo_url=wizard_state.repoUrl or None,
        )

        mode = wizard_state.mode
        drives = {d.physical_drive_id: d for d in platform_io.enumerate_removable_drives()}

        if mode in ("both", "master_only"):
            master_drive = drives.get(wizard_state.masterDriveId)
        if mode in ("both", "slave_only"):
            slave_drive = drives.get(wizard_state.slaveDriveId)

        if mode == "both":
            master_src = open_image(wizard_state.masterImagePath)
            slave_src = open_image(wizard_state.slaveImagePath)
            return PairFlashJob(
                master_image=master_src,
                slave_image=slave_src,
                master_target=master_drive,
                slave_target=slave_drive,
                firstboot_config=firstboot,
                platform_io=platform_io,
            )
        elif mode == "master_only":
            master_src = open_image(wizard_state.masterImagePath)
            return FlashJob(
                image=master_src,
                target=master_drive,
                role=Role.MASTER,
                firstboot_config=firstboot,
                platform_io=platform_io,
            )
        else:  # slave_only
            slave_src = open_image(wizard_state.slaveImagePath)
            return FlashJob(
                image=slave_src,
                target=slave_drive,
                role=Role.SLAVE,
                firstboot_config=firstboot,
                platform_io=platform_io,
            )
    except Exception as exc:
        import sys
        print(f"[FlashViewModel] _build_flash_job failed: {exc}", file=sys.stderr)
        return None
