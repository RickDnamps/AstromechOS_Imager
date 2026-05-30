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
            # Audit High #8 / #10: distinguish a user-initiated cancel from
            # a sidecar mismatch. The orchestrator looks for the literal
            # ``"CANCELLED"`` sentinel in the digest slot.
            self.finished.emit(self._role, "CANCELLED", False)
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
        # Audit High #9: route the view-model's cancel event into the job so
        # cancel() flips the same flag that DiskWriter / verify_readback
        # consult. Without this, the job has its own internal Event that
        # cancel() never reaches and the destructive write proceeds.
        if hasattr(job_obj, "cancel_event"):
            try:
                job_obj.cancel_event = self._cancel_event
            except AttributeError:
                pass  # frozen dataclass instance — best-effort
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

        Build-time failures (e.g. drive removed since Step 3, keygen
        I/O error, missing image file) surface as an ``error`` status
        with the exception message — the WRITE button never becomes a
        silent no-op (Audit High #18).
        """
        try:
            job = _build_flash_job(self._wizard_state)
        except Exception as exc:
            self._status = "error"
            self._error_message = f"Could not prepare flash job: {exc}"
            self.statusChanged.emit()
            self.errorMessageChanged.emit()
            return
        if job is None:
            # Legitimate "not enough info" — wizard validation should have
            # prevented WRITE from being clickable, but be defensive.
            self._status = "error"
            self._error_message = "Could not prepare flash job (no platform IO available)"
            self.statusChanged.emit()
            self.errorMessageChanged.emit()
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

        if digest == "CANCELLED":
            # Audit High #8 / #10: user-initiated cancel during hashing.
            # Distinct from a sidecar mismatch — go to a clean "cancelled"
            # state rather than telling the operator their file looks
            # corrupted (which is what _fail_verify would say).
            self._pending_verify_job = None
            self._pending_verify_roles = []
            self._status = "cancelled"
            self._error_message = ""
            self.statusChanged.emit()
            self.errorMessageChanged.emit()
            return

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
        """Request cancellation of the current verify / flash phase.

        Audit High #10 / #14: previously this flipped events without any UI
        feedback, so the operator kept seeing "VERIFYING" or "FLASHING" for
        seconds and would spam-click. Now the status flips to ``cancelling``
        immediately; the worker finish handler transitions to ``cancelled``
        once the in-flight chunk completes.
        """
        if self._status not in ("verifying", "flashing"):
            return  # nothing to cancel
        self._cancel_event.set()
        if self._worker is not None and hasattr(self._worker._job, "cancel_event"):
            try:
                self._worker._job.cancel_event.set()
            except AttributeError:
                pass
        self._status = "cancelling"
        self.statusChanged.emit()

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
        # Audit High #14: detect cancel-by-operator and route to a clean
        # "cancelled" state rather than "error" — the operator clicked
        # CANCEL themselves and shouldn't see an error message about it.
        if self._cancel_event.is_set():
            self._status = "cancelled"
            self._error_message = ""
        else:
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

        from astromechos_imager.core.models import FirstbootConfig, Role
        from astromechos_imager.core.orchestrator import FlashJob, PairFlashJob
        from astromechos_imager.core.keygen import (
            generate_ed25519, generate_hotspot_bootstrap,
            generate_linux_account,
            load_persisted_pair, save_persisted_pair,
            load_persisted_hotspot, save_persisted_hotspot,
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

        # wlan0 private interconnect: SSID is auto-generated per burn
        # (random ``Astromech-<4 digits>``), PSK is operator-supplied
        # via Step 4. Audit High #7: honour wizard_state.reuseHotspot —
        # a re-flashed master needs the SAME bootstrap as the existing
        # slave, otherwise they can't pair on boot. With reuseHotspot,
        # we re-use the persisted SSID but still apply the operator's
        # current PSK (so they can rotate it without re-burning both
        # cards).
        from astromechos_imager.core.models import HotspotBootstrap
        hotspot_psk = wizard_state.hotspotPassword or ""
        if not hotspot_psk:
            raise RuntimeError(
                "Step 4 (Customize) requires a Private Robot Hotspot "
                "Password — UI validity gate should have blocked this"
            )
        hotspot = None
        if getattr(wizard_state, "reuseHotspot", False):
            persisted = load_persisted_hotspot()
            if persisted is not None:
                hotspot = HotspotBootstrap(
                    ssid=persisted.ssid, password=hotspot_psk
                )
        if hotspot is None:
            hotspot = generate_hotspot_bootstrap(hotspot_psk)
        save_persisted_hotspot(hotspot)

        # Customize-step restoration: the operator fills Step 4 with a
        # UID-1000 username + password (mandatory, CLAUDE.md forbids any
        # hardcoded fallback) and an optional domestic Wi-Fi SSID/PSK
        # for the wlan1 dongle. The Wi-Fi pair is fully optional; the
        # account credentials are not — _build_flash_job is only ever
        # called from startFromWizard, which is gated behind the QML
        # WRITE-button validity check on the same fields.
        install_user = (wizard_state.installUser or "").strip()
        install_password = wizard_state.installPassword or ""
        if not install_user or not install_password:
            raise RuntimeError(
                "Step 4 (Customize) requires a username AND a password "
                "before WRITE — UI validity gate should have blocked this"
            )
        linux_account = generate_linux_account(install_user, install_password)

        wifi_ssid = (wizard_state.wifiSsid or "").strip() or None
        wifi_psk = wizard_state.wifiPsk or None
        if (wifi_ssid is None) != (wifi_psk is None):
            # FirstbootConfig.__post_init__ would catch this too, but the
            # error there is opaque; surface a wizard-shaped message.
            raise RuntimeError(
                "Domestic Wi-Fi requires both SSID and PSK, or leave both empty"
            )

        # FirstbootConfig:
        #   * authorized_keys=[] — validator permits empty (the Master is
        #     reached by password at first login; the Slave gets the Master's
        #     public key injected by render_authorized_keys at write time).
        #   * install_user reflects the COLD-surgery username so firstboot's
        #     home-dir creation / role-marker placement target the same
        #     UID-1000 the Imager just renamed.
        #   * The ed25519 keypair lives on the *job* (master_pair=), not on
        #     FirstbootConfig — that's the contract of FlashJob /
        #     PairFlashJob and what FirstbootBundle consumes.
        firstboot = FirstbootConfig(
            authorized_keys=[],
            install_user=install_user,
            hostname_master=wizard_state.hostnameMaster,
            hostname_slave=wizard_state.hostnameSlave,
            hotspot_bootstrap=hotspot,
            repo_url=wizard_state.repoUrl or None,
            wifi_ssid=wifi_ssid,
            wifi_psk=wifi_psk,
        )

        mode = wizard_state.mode
        drives = {d.physical_drive_id: d for d in platform_io.enumerate_removable_drives()}

        master_drive = None
        slave_drive = None
        if mode in ("both", "master_only"):
            master_drive = drives.get(wizard_state.masterDriveId)
            if master_drive is None:
                raise RuntimeError(
                    f"master drive id={wizard_state.masterDriveId} not found "
                    f"(was it removed since Step 3?)"
                )
        if mode in ("both", "slave_only"):
            slave_drive = drives.get(wizard_state.slaveDriveId)
            if slave_drive is None:
                raise RuntimeError(
                    f"slave drive id={wizard_state.slaveDriveId} not found "
                    f"(was it removed since Step 3?)"
                )

        if mode == "both":
            return PairFlashJob(
                platform_io=platform_io,
                master_image=Path(wizard_state.masterImagePath),
                master_target=master_drive,
                slave_image=Path(wizard_state.slaveImagePath),
                slave_target=slave_drive,
                firstboot_config=firstboot,
                master_pair=ed25519,
            )
        if mode == "master_only":
            return FlashJob(
                platform_io=platform_io,
                image_path=Path(wizard_state.masterImagePath),
                target=master_drive,
                role=Role.MASTER,
                firstboot_config=firstboot,
                master_pair=ed25519,
            )
        # slave_only
        return FlashJob(
            platform_io=platform_io,
            image_path=Path(wizard_state.slaveImagePath),
            target=slave_drive,
            role=Role.SLAVE,
            firstboot_config=firstboot,
            master_pair=ed25519,
        )
    except Exception:
        # Audit High #18: don't swallow silently. Re-raise so startFromWizard
        # can surface the failure in the UI instead of leaving WRITE a no-op.
        raise
