"""Bridges PairFlashJob / FlashJob to QML. Runs the job in a QThread.

The exposed state machine is:

    idle → verifying → flashing → done
                  └→ error
            ↑
        startFromWizard()

Verifying is the pre-flash SHA-256 / MD5 check (skipped when
``wizardState.verifyIntegrity`` is False). Each image is hashed in its
own dedicated _HashWorker on a fresh QThread; mismatch against a sidecar
file (``image.sha256`` / ``image.md5``) jumps straight to ``error``.
When no sidecar exists the digest is exposed via ``masterHash`` /
``slaveHash`` and the operator confirms visually before flashing.
"""
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


class _HashWorker(QObject):
    """Streams hashlib over a compressed image, emits progress + result.

    ``sidecar`` is the (algo, expected_hex_lower) pair found next to the
    image, or None when no sidecar file exists. ``role`` is the wizard
    role string ('master' / 'slave') so the orchestrator can route the
    result to the right progress channel."""

    progress = Signal(str, float)          # role, fraction 0..1
    finished = Signal(str, str, "QVariant") # role, hex_hash, sidecar_match (bool|None)

    def __init__(
        self,
        image_path: Path,
        role: str,
        sidecar: tuple[str, str] | None,
        cancel_event: threading.Event,
    ):
        super().__init__()
        self._path = image_path
        self._role = role
        self._sidecar = sidecar
        self._cancel = cancel_event

    @Slot()
    def run(self) -> None:
        from astromechos_imager.core.image_validator import (
            hash_compressed_file, HashCancelled,
        )
        algo = self._sidecar[0] if self._sidecar else "sha256"
        try:
            digest = hash_compressed_file(
                self._path,
                algo=algo,
                progress_cb=lambda f: self.progress.emit(self._role, f),
                cancel_event=self._cancel,
            )
        except HashCancelled:
            self.finished.emit(self._role, "", False)
            return
        except Exception as exc:
            self.finished.emit(self._role, f"ERR:{type(exc).__name__}:{exc}", False)
            return
        if self._sidecar is None:
            match = None
        else:
            match = (digest.lower() == self._sidecar[1].lower())
        self.finished.emit(self._role, digest, match)


class FlashViewModel(QObject):
    """Top-level controller for the flash step. Owns the QThread + worker."""
    statusChanged = Signal()
    masterProgressChanged = Signal()
    masterPhaseChanged = Signal()
    slaveProgressChanged = Signal()
    slavePhaseChanged = Signal()
    errorMessageChanged = Signal()
    # Integrity verification (pre-flash hash phase)
    masterHashProgressChanged = Signal()
    slaveHashProgressChanged = Signal()
    masterHashChanged = Signal()
    slaveHashChanged = Signal()
    masterHashSidecarMatchChanged = Signal()   # bool|None as JS value
    slaveHashSidecarMatchChanged = Signal()

    def __init__(self, wizard_state, parent=None):
        super().__init__(parent)
        self._wizard_state = wizard_state
        self._status = "idle"               # idle | verifying | flashing | done | error
        self._master_progress = 0.0
        self._master_phase = ""
        self._slave_progress = 0.0
        self._slave_phase = ""
        self._error_message = ""
        self._thread: QThread | None = None
        self._worker: _FlashWorker | None = None
        self._cancel_event = threading.Event()
        # Pre-flash hashing state
        self._master_hash_progress = 0.0
        self._slave_hash_progress = 0.0
        self._master_hash = ""
        self._slave_hash = ""
        self._master_hash_sidecar_match = None   # True | False | None
        self._slave_hash_sidecar_match = None
        self._hash_thread: QThread | None = None
        self._hash_worker: _HashWorker | None = None
        self._pending_verify_job = None        # cached job from startFromWizard
        self._pending_verify_roles: list[str] = []  # roles still to hash

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

    # ── Pre-flash hash phase properties ───────────────────────────────

    @Property(float, notify=masterHashProgressChanged)
    def masterHashProgress(self) -> float:
        return self._master_hash_progress

    @Property(float, notify=slaveHashProgressChanged)
    def slaveHashProgress(self) -> float:
        return self._slave_hash_progress

    @Property(str, notify=masterHashChanged)
    def masterHash(self) -> str:
        return self._master_hash

    @Property(str, notify=slaveHashChanged)
    def slaveHash(self) -> str:
        return self._slave_hash

    @Property("QVariant", notify=masterHashSidecarMatchChanged)
    def masterHashSidecarMatch(self):
        return self._master_hash_sidecar_match

    @Property("QVariant", notify=slaveHashSidecarMatchChanged)
    def slaveHashSidecarMatch(self):
        return self._slave_hash_sidecar_match

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

        If ``wizardState.verifyIntegrity`` is True (default), runs SHA-256
        on each compressed image first, compares to the sidecar when
        present, and only proceeds to the actual flash on success. On a
        hash mismatch the wizard short-circuits to ``error`` and the
        operator never reaches the destructive write phase.
        """
        job = _build_flash_job(self._wizard_state)
        if job is None:
            return
        if not getattr(self._wizard_state, "verifyIntegrity", True):
            self.startWithJob(job)
            return
        self._begin_verify_phase(job)

    def _begin_verify_phase(self, job) -> None:
        """Stage the queue of images to hash, then start the first worker.

        For a paired flash we serialise master then slave on the same
        QThread — the alternative (two parallel hashers) would double the
        I/O queue depth for no real wall-clock gain on a typical NVMe.
        """
        if self._status in ("verifying", "flashing"):
            return
        self._status = "verifying"
        self._error_message = ""
        self._master_hash_progress = 0.0
        self._slave_hash_progress = 0.0
        self._master_hash = ""
        self._slave_hash = ""
        self._master_hash_sidecar_match = None
        self._slave_hash_sidecar_match = None
        self.statusChanged.emit()
        self.errorMessageChanged.emit()
        for sig in (
            self.masterHashProgressChanged, self.slaveHashProgressChanged,
            self.masterHashChanged, self.slaveHashChanged,
            self.masterHashSidecarMatchChanged, self.slaveHashSidecarMatchChanged,
        ):
            sig.emit()

        # Figure out which images need hashing — derived from the wizard
        # mode so we don't hash a path that won't be flashed.
        mode = self._wizard_state.mode
        queue: list[str] = []
        if mode in ("both", "master_only"):
            queue.append("master")
        if mode in ("both", "slave_only"):
            queue.append("slave")
        self._pending_verify_job = job
        self._pending_verify_roles = queue
        self._cancel_event.clear()
        self._spawn_next_hash_worker()

    def _spawn_next_hash_worker(self) -> None:
        from astromechos_imager.core.image_validator import find_sidecar_checksum
        if not self._pending_verify_roles:
            # All queued hashes done — chain to actual flash.
            job = self._pending_verify_job
            self._pending_verify_job = None
            if job is not None:
                self.startWithJob(job)
            return
        role = self._pending_verify_roles[0]
        path_s = (
            self._wizard_state.masterImagePath if role == "master"
            else self._wizard_state.slaveImagePath
        )
        path = Path(path_s)
        sidecar = find_sidecar_checksum(path)
        self._hash_thread = QThread()
        self._hash_worker = _HashWorker(path, role, sidecar, self._cancel_event)
        self._hash_worker.moveToThread(self._hash_thread)
        self._hash_worker.progress.connect(self._on_hash_progress)
        self._hash_worker.finished.connect(self._on_hash_finished)
        self._hash_thread.started.connect(self._hash_worker.run)
        self._hash_thread.start()

    def _on_hash_progress(self, role: str, frac: float) -> None:
        if role == "master":
            self._master_hash_progress = frac
            self.masterHashProgressChanged.emit()
        else:
            self._slave_hash_progress = frac
            self.slaveHashProgressChanged.emit()

    def _on_hash_finished(self, role: str, digest: str, match) -> None:
        # Always tear down the worker thread before deciding what's next.
        if self._hash_thread is not None:
            self._hash_thread.quit()
            self._hash_thread.wait(500)
            self._hash_thread = None
            self._hash_worker = None

        if digest.startswith("ERR:"):
            # Worker raised — abort the verify phase entirely.
            self._fail_verify(f"hash failed for {role} image: {digest[4:]}")
            return

        if role == "master":
            self._master_hash = digest
            self._master_hash_sidecar_match = match
            self.masterHashChanged.emit()
            self.masterHashSidecarMatchChanged.emit()
        else:
            self._slave_hash = digest
            self._slave_hash_sidecar_match = match
            self.slaveHashChanged.emit()
            self.slaveHashSidecarMatchChanged.emit()

        if match is False:
            # Sidecar mismatch — refuse to flash.
            self._fail_verify(
                f"SHA-256 mismatch on {role} image — file looks corrupted"
            )
            return

        # Either match==True (sidecar OK) or match is None (no sidecar,
        # operator will eyeball the hash). Either way, move on.
        self._pending_verify_roles.pop(0)
        self._spawn_next_hash_worker()

    def _fail_verify(self, msg: str) -> None:
        self._pending_verify_job = None
        self._pending_verify_roles = []
        self._status = "error"
        self._error_message = msg
        self.statusChanged.emit()
        self.errorMessageChanged.emit()

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
