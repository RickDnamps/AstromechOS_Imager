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
from astromechos_imager.core.models import HotspotBootstrap, Role


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
        # Fire a "preparing" phase ping immediately when the worker thread
        # starts, BEFORE job.run() blocks for ~1-3 s on lock_and_dismount /
        # open_raw_device / open_image. Without this, the UI sits at
        # status="flashing" + progress 0% + empty phase label for the entire
        # silent window — indistinguishable from "Not Responding". With this
        # ping, Step5Flash.qml can render "Preparing target drive…" with an
        # indeterminate spinner until DiskWriter starts firing real chunks.
        if self._is_pair:
            self.progressMaster.emit(0.0, "preparing")
            self.progressSlave.emit(0.0, "preparing")
        else:
            self.progressMaster.emit(0.0, "preparing")

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
    # Sequential Deployment Assistant: the hotspot SSID is generated ONCE
    # per session by startSession() (Screen 01 Landing) and baked into
    # BOTH cards so the runtime master-slave handshake works. UI binds to
    # this for the persistent "Session hotspot: Astromech-XXXX" header.
    sessionSsidChanged = Signal(str)

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
        # Session-scoped hotspot — generated ONCE by startSession() on
        # Screen 01 Landing and reused for every flash in the session so
        # both master and slave cards carry the SAME SSID + PSK into
        # /boot/astromech_init.cfg. None until startSession() runs.
        self._session_hotspot: HotspotBootstrap | None = None

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

    # ── Sequential session ────────────────────────────────────────────
    #
    # The session hotspot SSID is generated ONCE on Screen 01 Landing
    # and persists across both flash cycles so the master/slave pair
    # boots into the same wlan0 rendezvous. The PSK still falls back to
    # ``astropass`` if Step 2 Config hasn't been visited yet — Step 2's
    # save handler will refresh _session_hotspot if the operator types
    # a different one.

    @Property(str, notify=sessionSsidChanged)
    def sessionSsid(self) -> str:
        return self._session_hotspot.ssid if self._session_hotspot else ""

    @Slot()
    def startSession(self) -> None:
        """Wired to Screen 01 Landing 'Start Deployment' button. Idempotent.

        Generates the session-scoped hotspot bootstrap (random SSID +
        operator PSK with fallback to ``astropass``). Both flash cycles
        in this session inherit the SAME ssid so the runtime
        master/slave handshake works without re-flashing one card.
        """
        if self._session_hotspot is not None:
            return
        from astromechos_imager.core.keygen import generate_hotspot_bootstrap
        psk = "astropass"  # safe default; Step 2 Config will validate the real one
        if hasattr(self._wizard_state, "hotspotPassword"):
            raw = getattr(self._wizard_state, "hotspotPassword", "") or ""
            if len(raw) >= 8:
                psk = raw
        self._session_hotspot = generate_hotspot_bootstrap(psk)
        self.sessionSsidChanged.emit(self._session_hotspot.ssid)
        import logging
        logging.getLogger(__name__).info(
            "Sequential session started — hotspot SSID=%s (persists across both cycles)",
            self._session_hotspot.ssid,
        )

    @Slot()
    def endSession(self) -> None:
        """Reset the per-session state so the next deployment starts fresh.

        Wired to Step 7 Complete 'FLASH ANOTHER' button (audit bugs C3
        + H1). Without this, a second sequential session would reuse
        the previous run's SSID — both pairs would camp on the same
        wlan0 rendezvous and the second robot would never bind.
        """
        self._session_hotspot = None
        self.sessionSsidChanged.emit("")
        import logging
        logging.getLogger(__name__).info(
            "Sequential session ended — SSID cleared for next deployment"
        )

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
            job = _build_flash_job(
                self._wizard_state, session_hotspot=self._session_hotspot
            )
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

        # Sequential workflow flashes ONE role per cycle — derive the
        # queue from wizard_state.currentRole rather than the deleted
        # mode picker. Empty role is a guard against test entry that
        # skips Screen 4; defaults to "master" so something hashes.
        current_role = getattr(self._wizard_state, "currentRole", "") or "master"
        queue: list[str] = [current_role]
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
            # Sequential Deployment Assistant: advance the role state
            # machine on success ONLY. Idempotent — re-entry is safe.
            if ok and hasattr(self._wizard_state, "markCurrentRoleCompleted"):
                try:
                    self._wizard_state.markCurrentRoleCompleted()
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception(
                        "markCurrentRoleCompleted() raised; flash succeeded "
                        "but the sequential state machine did not advance"
                    )
        self.statusChanged.emit()
        self.errorMessageChanged.emit()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(500)
            self._thread = None
            self._worker = None


# ── Non-blocking fallback defaults ────────────────────────────────────
# Single source of truth for "what the Imager writes to the SD card when
# the operator leaves Step 4 fields blank". The Pi-side scripts also know
# about ``astromech`` (live ``firstboot_setup.sh:97`` waterfall +
# ``lib_config.sh::capture_user`` prefer it over the legacy ``artoo``);
# the two sides are kept in lockstep so an Imager-flashed card with
# defaults gives the operator the same SSH login on every robot.
#
# ``astropass`` is 9 chars = compliant with IEEE 802.11i WPA2-PSK (≥8)
# enforced by ``firstboot_setup.sh:382`` and ``astromech_wlan_setup.sh:110``,
# so the wlan0 bootstrap rendezvous never silently brick-skips when the
# operator keeps the default.
DEFAULT_INSTALL_USER     = "astromech"
DEFAULT_INSTALL_PASSWORD = "astropass"
DEFAULT_HOTSPOT_PASSWORD = "astropass"


def _build_flash_job(wizard_state, platform_io=None, session_hotspot=None):
    """Build a FlashJob from wizard_state fields for the current cycle.

    Sequential Deployment Assistant: each cycle flashes ONE role
    (master OR slave) — driven by ``wizard_state.currentRole``. The
    deleted MODE picker would have collapsed to ``master_only`` /
    ``slave_only`` in the old flow; ``currentRole`` is its successor.

    Step 2 Config fields are NON-BLOCKING: empty strings on
    ``installUser`` / ``installPassword`` / ``hotspotPassword`` are
    silently substituted with the module-level ``DEFAULT_*`` constants
    above. This guarantees ``/boot/astromech_init.cfg`` is always
    complete on the SD card, no matter how the operator went through
    the wizard.

    ``session_hotspot`` is the session-scoped HotspotBootstrap generated
    once on Screen 01 Landing and reused for every cycle so master/slave
    boot into the SAME wlan0 rendezvous. When None (legacy test entry
    that skips Screen 01), a fresh bootstrap is generated locally.

    Returns None if construction fails because no platform IO is
    available (non-Windows host without an injected fake). Otherwise
    re-raises construction errors so the WRITE button never becomes a
    silent no-op (Audit High #18). This function is module-level so it
    can be unit-tested with a fake wizard_state.
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
        from astromechos_imager.core.orchestrator import FlashJob
        from astromechos_imager.core.keygen import (
            generate_ed25519, generate_hotspot_bootstrap,
            generate_linux_account,
            load_persisted_pair, save_persisted_pair,
            save_persisted_hotspot,
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

        # Non-blocking fallback: empty UI fields trigger the module-level
        # DEFAULT_* substitution. Operator-supplied values WIN; blank
        # values get the safe defaults (astromech / astropass). This
        # guarantees ``[hotspot]`` and ``[system]`` blocks in
        # ``/boot/astromech_init.cfg`` are always complete and ≥8 chars
        # (no firstboot brick-skip on the Pi).
        install_user     = (wizard_state.installUser or "").strip()     or DEFAULT_INSTALL_USER
        install_password = (wizard_state.installPassword or "")         or DEFAULT_INSTALL_PASSWORD
        hotspot_psk      = (wizard_state.hotspotPassword or "")         or DEFAULT_HOTSPOT_PASSWORD

        linux_account = generate_linux_account(install_user, install_password)

        # SSID is session-scoped — generated ONCE by startSession() on
        # Screen 01. The SAME hotspot creds are baked into both master
        # and slave's /boot/astromech_init.cfg so the runtime master-
        # slave handshake works.
        if session_hotspot is None:
            # Defensive: legacy code paths (or test entry that skips
            # Screen 01) — still generate. PSK falls back to "astropass"
            # per generate_hotspot_bootstrap's WPA2 minimum.
            psk_fallback = hotspot_psk or "astropass"
            if len(psk_fallback) < 8:
                psk_fallback = "astropass"
            session_hotspot = generate_hotspot_bootstrap(psk_fallback)
        # The session SSID carries through; the PSK still honours any
        # operator-typed value (so they can rotate without losing the
        # SSID continuity that lets master/slave pair).
        hotspot = HotspotBootstrap(
            ssid=session_hotspot.ssid,
            password=hotspot_psk,
        )
        save_persisted_hotspot(hotspot)

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

        # Sequential workflow: one cycle = one role = one FlashJob. The
        # role is set on Screen 4 via wizard_state.setCurrentRole().
        current_role = (getattr(wizard_state, "currentRole", "") or "").strip()
        if current_role not in ("master", "slave"):
            raise RuntimeError(
                "Cannot build flash job: wizard_state.currentRole must be "
                "'master' or 'slave' (got %r). Screen 4 Role must run first."
                % current_role
            )

        drives = {d.physical_drive_id: d for d in platform_io.enumerate_removable_drives()}

        if current_role == "master":
            drive = drives.get(wizard_state.masterDriveId)
            if drive is None:
                raise RuntimeError(
                    f"master drive id={wizard_state.masterDriveId} not found "
                    f"(was it removed since Step 3?)"
                )
            return FlashJob(
                platform_io=platform_io,
                image_path=Path(wizard_state.masterImagePath),
                target=drive,
                role=Role.MASTER,
                firstboot_config=firstboot,
                master_pair=ed25519,
                linux_account=linux_account,
            )
        # current_role == "slave"
        drive = drives.get(wizard_state.slaveDriveId)
        if drive is None:
            raise RuntimeError(
                f"slave drive id={wizard_state.slaveDriveId} not found "
                f"(was it removed since Step 3?)"
            )
        return FlashJob(
            platform_io=platform_io,
            image_path=Path(wizard_state.slaveImagePath),
            target=drive,
            role=Role.SLAVE,
            firstboot_config=firstboot,
            master_pair=ed25519,
            linux_account=linux_account,
        )
    except Exception:
        # Audit High #18: don't swallow silently. Re-raise so startFromWizard
        # can surface the failure in the UI instead of leaving WRITE a no-op.
        raise
