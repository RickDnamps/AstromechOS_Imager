"""Bridges FlashJob to QML. Runs the job in a QThread.

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

import contextlib
import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QThread, Signal, Slot

from astromechos_imager.core.diskwriter import DiskWriterProgress
from astromechos_imager.core.models import HotspotBootstrap, Role

#: UI progress is rate-gated to this period per channel. The flash worker can
#: fire progress per buffer (hundreds/sec); the GUI only needs ~12 Hz, and a
#: tighter cadence just floods the render thread (jank while dragging).
_PROGRESS_MIN_INTERVAL_S = 1.0 / 12.0


class _FlashWorker(QObject):
    """Lives in a QThread; runs job.run() then emits 'finished'.

    progress* signals are (fraction 0..1, phase, throughput_bps); throughput is
    0.0 for non-bandwidth events so the bar hides the speed badge. The two
    channels exist because the sequential workflow routes a single job's
    progress to the bar matching its role (master cycle vs slave cycle).
    """
    progressMaster = Signal(float, str, float)
    progressSlave = Signal(float, str, float)
    finished = Signal(bool, str)          # ok, error_msg
    phaseChanged = Signal(str, str)       # role_value, phase_str

    def __init__(self, job):
        super().__init__()
        self._job = job
        # Per-channel rate-gate state, pre-seeded so updates only ever mutate
        # existing keys (GIL-safe).
        self._last_emit = {"m": 0.0, "s": 0.0}
        self._last_phase = {"m": "", "s": ""}

    @Slot()
    def run(self) -> None:
        # Show activity immediately during the ~1-3 s silent window before
        # DiskWriter starts firing chunks.
        self._single_sig().emit(0.0, "preparing", 0.0)
        try:
            self._job.on_progress = self._on_single_progress
            result = self._job.run()
            ok = bool(result.ok)
            err = "" if ok else str(getattr(result, "error", "")) or "flash failed"
            # finished is never gated — completion always reaches the UI (which
            # then forces the bar to 100% via the done state).
            self.finished.emit(ok, err)
        except Exception as e:
            self.finished.emit(False, f"{type(e).__name__}: {e}")

    def _gate(self, key: str, phase: str) -> bool:
        """True if this update should reach the UI: always on a phase change,
        else at most once per _PROGRESS_MIN_INTERVAL_S."""
        now = time.monotonic()
        if (
            phase != self._last_phase[key]
            or (now - self._last_emit[key]) >= _PROGRESS_MIN_INTERVAL_S
        ):
            self._last_phase[key] = phase
            self._last_emit[key] = now
            return True
        return False

    def _single_is_slave(self) -> bool:
        """A single FlashJob carries its own ``role`` — route its progress to
        the MATCHING channel.

        Step5Flash reads ``slaveProgress`` for a slave cycle and
        ``masterProgress`` for a master cycle, so the worker MUST emit on the
        channel matching the job's role. Routing by role keeps worker
        channel == UI channel, so the progress bar tracks the live write
        instead of freezing at 0%.
        """
        role = getattr(self._job, "role", None)
        return (role is Role.SLAVE) or (getattr(role, "value", role) == "slave")

    def _single_sig(self):
        return self.progressSlave if self._single_is_slave() else self.progressMaster

    def _on_single_progress(self, p: DiskWriterProgress) -> None:
        key = "s" if self._single_is_slave() else "m"
        if not self._gate(key, p.phase):
            return
        frac = (p.bytes_done / p.bytes_total) if p.bytes_total else 0.0
        self._single_sig().emit(frac, p.phase, p.throughput_bps)


class _HashWorker(QObject):
    """Streams hashlib over a compressed image, emits progress + result.

    ``sidecar`` is the ``(algo, expected_hex_lower, sidecar_path)`` tuple
    found next to the image, or None when no sidecar file exists. ``role``
    is the wizard role string ('master' / 'slave') so the orchestrator
    can route the result to the right progress channel."""

    progress = Signal(str, float)          # role, fraction 0..1
    finished = Signal(str, str, "QVariant") # role, hex_hash, sidecar_match (bool|None)

    def __init__(
        self,
        image_path: Path,
        role: str,
        sidecar: tuple[str, str, Path] | None,
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
            HashCancelled,
            hash_compressed_file,
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
            # Distinguish a user-initiated cancel from a sidecar mismatch.
            # The orchestrator looks for the literal ``"CANCELLED"`` sentinel
            # in the digest slot.
            self.finished.emit(self._role, "CANCELLED", False)
            return
        except Exception as exc:
            self.finished.emit(self._role, f"ERR:{type(exc).__name__}:{exc}", False)
            return
        match = (
            None if self._sidecar is None else digest.lower() == self._sidecar[1].lower()
        )
        self.finished.emit(self._role, digest, match)


class FlashViewModel(QObject):
    """Top-level controller for the flash step. Owns the QThread + worker."""
    statusChanged = Signal()
    masterProgressChanged = Signal()
    masterPhaseChanged = Signal()
    masterThroughputBpsChanged = Signal()
    slaveProgressChanged = Signal()
    slavePhaseChanged = Signal()
    slaveThroughputBpsChanged = Signal()
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
        self._master_throughput_bps = 0.0
        self._slave_progress = 0.0
        self._slave_phase = ""
        self._slave_throughput_bps = 0.0
        self._error_message = ""
        self._thread: QThread | None = None
        self._worker: _FlashWorker | None = None
        self._cancel_event = threading.Event()
        # Distinguishes "user clicked CANCEL" from "DiskWriter consumer
        # died and set cancel_event as a thread-coordination side-effect"
        # (diskwriter.py::run consumer ``except BaseException`` branch).
        # Without this flag, ``_on_finished`` mis-routes real write
        # failures to status="cancelled" — the QML has no dedicated
        # rendering for that status so it falls through to the idle
        # screen, the WRITE button re-appears, and the operator never
        # sees the actual error.
        self._user_cancelled = False
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
        # Per-role sidecar tuple (algo, expected_hex, sidecar_path) cached
        # at spawn time so _on_hash_finished can produce a detailed
        # operator-facing mismatch error WITHOUT re-scanning the disk.
        # Stale-sidecar misdiagnosis is the #1 reason a healthy golden
        # image gets blamed for "corruption" — see _fail_verify_with_detail.
        self._master_sidecar: tuple[str, str, Path] | None = None
        self._slave_sidecar: tuple[str, str, Path] | None = None
        # The wlan0 bootstrap SSID lives on wizard_state.hotspotSsid (minted at
        # init, regenerated on endSession) — the FlashViewModel no longer owns
        # or generates it. Single source of truth, no desync.

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(float, notify=masterProgressChanged)
    def masterProgress(self) -> float:
        return self._master_progress

    @Property(str, notify=masterPhaseChanged)
    def masterPhase(self) -> str:
        return self._master_phase

    @Property(float, notify=masterThroughputBpsChanged)
    def masterThroughputBps(self) -> float:
        """Live write/verify throughput for the master card in bytes/sec.

        Reset to 0.0 between phases (verify entry, post-flash). QML
        ``GlobalProgressBar`` hides its "Mo/s" badge when this is 0 so
        non-bandwidth phases (preparing / customizing / hash verify)
        don't display a misleading speed.
        """
        return self._master_throughput_bps

    @Property(float, notify=slaveProgressChanged)
    def slaveProgress(self) -> float:
        return self._slave_progress

    @Property(str, notify=slavePhaseChanged)
    def slavePhase(self) -> str:
        return self._slave_phase

    @Property(float, notify=slaveThroughputBpsChanged)
    def slaveThroughputBps(self) -> float:
        """Live write/verify throughput for the slave card in bytes/sec."""
        return self._slave_throughput_bps

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
    # The wlan0 bootstrap SSID now lives on ``wizard_state.hotspotSsid``
    # (minted at init, regenerated by wizard_state.endSession()), so the
    # FlashViewModel no longer owns, generates, or exposes it — single source
    # of truth, no recalculation, no desync. All screens bind to
    # ``wizardState.hotspotSsid`` directly.

    @Slot()
    def resetForNextCycle(self) -> None:
        """Reset the per-CYCLE flash UI state so the next card starts fresh.

        Wired to Step 6 'CONTINUE / insert next card' (alongside
        ``wizardState.resetForNextCycle()``). Without this the status stays
        ``done`` from the previous card, so Step 5 renders the "already
        flashed" state for the next card instead of going back to a clean
        READY-to-write / Validating-source start. The bootstrap SSID
        (``wizardState.hotspotSsid``) is deliberately PRESERVED across the
        cycle — it is shared across both cards of the pair.
        """
        self._status = "idle"
        self._error_message = ""
        self._master_progress = 0.0
        self._slave_progress = 0.0
        self._master_phase = ""
        self._slave_phase = ""
        self._master_throughput_bps = 0.0
        self._slave_throughput_bps = 0.0
        self._master_hash_progress = 0.0
        self._slave_hash_progress = 0.0
        self._master_hash = ""
        self._slave_hash = ""
        self._master_hash_sidecar_match = None
        self._slave_hash_sidecar_match = None
        self._user_cancelled = False
        self._cancel_event.clear()
        # Verify-phase plumbing: clear the sidecar tuples and the pending job
        # so card 1's verify context can never leak into the next card.
        self._pending_verify_job = None
        self._pending_verify_roles = []
        self._master_sidecar = None
        self._slave_sidecar = None
        for sig in (
            self.statusChanged, self.errorMessageChanged,
            self.masterProgressChanged, self.masterPhaseChanged,
            self.masterThroughputBpsChanged,
            self.slaveProgressChanged, self.slavePhaseChanged,
            self.slaveThroughputBpsChanged,
            self.masterHashProgressChanged, self.slaveHashProgressChanged,
            self.masterHashChanged, self.slaveHashChanged,
            self.masterHashSidecarMatchChanged, self.slaveHashSidecarMatchChanged,
        ):
            sig.emit()

    @Slot(result=str)
    def exportDiagnostic(self) -> str:
        """Write a redacted support bundle next to the operator's Downloads.

        Builds the diagnostic ZIP via logging_setup/diagnostic.py. Returns
        the ZIP path on success, or an ``ERROR: …`` string the QML label
        shows verbatim. PSKs/passwords are stripped by the redactor.
        """
        import os
        import time as _time

        from astromechos_imager.logging_setup.diagnostic import (
            build_diagnostic_zip,
            collect_system_info,
        )
        try:
            appdata = os.environ.get("APPDATA") or str(Path.home())
            log_dir = Path(appdata) / "AstromechOS Imager" / "logs"
            logs = sorted(log_dir.glob("flash-*.log")) if log_dir.is_dir() else []
            log_path = logs[-1] if logs else log_dir / "missing.log"
            downloads = Path.home() / "Downloads"
            out_dir = downloads if downloads.is_dir() else Path.home()
            stamp = _time.strftime("%Y%m%d-%H%M%S")
            target = out_dir / f"AstromechOS_Imager_diagnostic_{stamp}.zip"
            cfg = {
                "hostname_master": getattr(self._wizard_state, "hostnameMaster", ""),
                "hostname_slave": getattr(self._wizard_state, "hostnameSlave", ""),
                "repo_url": getattr(self._wizard_state, "repoUrl", ""),
                "hotspot_ssid": getattr(self._wizard_state, "hotspotSsid", ""),
            }
            build_diagnostic_zip(
                target=target,
                log_path=log_path,
                traceback_text=self._error_message,
                system_info=collect_system_info(),
                firstboot_config=cfg,
            )
            return str(target)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("diagnostic export failed")
            return f"ERROR: {type(exc).__name__}: {exc}"

    @Slot(QObject)
    def startWithJob(self, job_obj) -> None:
        """job_obj should be a Python object exposing the FlashJob interface.
        In tests we pass FakeJob; in production app.build_app() wires a real
        factory that constructs from wizardState."""
        if self._status == "flashing":
            return
        self._cancel_event.clear()
        self._user_cancelled = False
        # Route the view-model's cancel event into the job so cancel() flips
        # the same flag that DiskWriter / verify_readback consult. Without
        # this, the job has its own internal Event that cancel() never reaches
        # and the destructive write proceeds.
        if hasattr(job_obj, "cancel_event"):
            # Frozen dataclass instance — best-effort.
            with contextlib.suppress(AttributeError):
                job_obj.cancel_event = self._cancel_event
        self._status = "flashing"
        self.statusChanged.emit()
        self._thread = QThread()
        self._worker = _FlashWorker(job_obj)
        self._worker.moveToThread(self._thread)
        self._worker.progressMaster.connect(self._update_master)
        self._worker.progressSlave.connect(self._update_slave)
        self._worker.finished.connect(self._on_finished)
        self._thread.started.connect(self._worker.run)
        self._thread.start()

    @Slot()
    def startFromWizard(self) -> None:
        """Build the FlashJob from wizardState + platform IO, then start.

        If ``wizardState.verifyIntegrity`` is True (default), runs SHA-256
        on each compressed image first, compares to the sidecar when
        present, and only proceeds to the actual flash on success. On a
        hash mismatch the wizard short-circuits to ``error`` and the
        operator never reaches the destructive write phase.

        Build-time failures (e.g. drive removed since Step 3, keygen
        I/O error, missing image file) surface as an ``error`` status
        with the exception message — the WRITE button never becomes a
        silent no-op.
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
        # Reset live throughput so the GlobalProgressBar's "Mo/s" badge
        # disappears across a verify-phase transition. Without this the
        # last-known flash speed would briefly leak into the hash phase
        # before DiskWriter starts re-sampling.
        self._master_throughput_bps = 0.0
        self._slave_throughput_bps = 0.0
        self.masterThroughputBpsChanged.emit()
        self.slaveThroughputBpsChanged.emit()
        self.statusChanged.emit()
        self.errorMessageChanged.emit()
        for sig in (
            self.masterHashProgressChanged, self.slaveHashProgressChanged,
            self.masterHashChanged, self.slaveHashChanged,
            self.masterHashSidecarMatchChanged, self.slaveHashSidecarMatchChanged,
        ):
            sig.emit()

        # Sequential workflow flashes ONE role per cycle — derive the queue
        # from wizard_state.currentRole. Empty role is a guard against test
        # entry that skips Screen 4; defaults to "master" so something hashes.
        current_role = getattr(self._wizard_state, "currentRole", "") or "master"
        queue: list[str] = [current_role]
        self._pending_verify_job = job
        self._pending_verify_roles = queue
        self._cancel_event.clear()
        self._user_cancelled = False
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
        # Cache the resolved sidecar tuple so that _on_hash_finished can
        # produce an actionable mismatch error (sidecar path + expected
        # hash) WITHOUT having to re-walk the filesystem.
        if role == "master":
            self._master_sidecar = sidecar
        else:
            self._slave_sidecar = sidecar
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

    def _park_overrun_thread(self, thread, worker) -> None:
        """Keep a reference to a QThread that missed its 500 ms join.

        Dropping the last Python reference to a still-RUNNING QThread lets
        the QThread object be destroyed under the live thread — a hard Qt
        fatal ("QThread: Destroyed while thread is still running"). Park the
        pair until the thread actually finishes; the list self-prunes on the
        next park, and a session parks at most a handful.
        """
        zombies = getattr(self, "_zombie_threads", None)
        if zombies is None:
            zombies = self._zombie_threads = []
        zombies[:] = [(t, w) for (t, w) in zombies if not t.isFinished()]
        zombies.append((thread, worker))

    def _on_hash_finished(self, role: str, digest: str, match) -> None:
        # Always tear down the worker thread before deciding what's next.
        if self._hash_thread is not None:
            self._hash_thread.quit()
            if not self._hash_thread.wait(500):
                self._park_overrun_thread(self._hash_thread, self._hash_worker)
            self._hash_thread = None
            self._hash_worker = None

        if digest == "CANCELLED":
            # User-initiated cancel during hashing. Distinct from a sidecar
            # mismatch — go to a clean "cancelled" state rather than telling
            # the operator their file looks corrupted (which is what
            # _fail_verify would say).
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
            # Sidecar mismatch — refuse to flash. Produce an actionable
            # error: operators routinely misdiagnose this as "the
            # customization step broke the image", but customization
            # writes ONLY to the SD card, NEVER to the source .img.gz.
            # The real cause is almost always a stale sidecar that
            # survived a golden-image regeneration.
            path_s = (
                self._wizard_state.masterImagePath if role == "master"
                else self._wizard_state.slaveImagePath
            )
            sidecar_tuple = (
                self._master_sidecar if role == "master"
                else self._slave_sidecar
            )
            if sidecar_tuple is not None:
                _algo, expected_hex, sidecar_path = sidecar_tuple
                self._fail_verify_with_detail(
                    role=role,
                    image_path=Path(path_s),
                    sidecar_path=sidecar_path,
                    expected_hex=expected_hex,
                    computed_hex=digest,
                )
            else:
                # Defensive: match==False should imply sidecar was found.
                # If we somehow got here without a cached sidecar tuple,
                # fall back to the simpler message rather than crash.
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

    def _fail_verify_with_detail(
        self,
        role: str,
        image_path: Path,
        sidecar_path: Path,
        expected_hex: str,
        computed_hex: str,
    ) -> None:
        """Surface a SHA-256 mismatch with operator-actionable detail.

        A bare "file looks corrupted" message sends operators down the
        wrong path — blaming the customization step, the SD card, or the
        writer when the actual cause is usually a stale ``.sha256`` sidecar
        that no longer matches a regenerated golden image. This helper names
        the sidecar file, shows both digests (truncated to 16 chars for
        readability), and gives the operator two concrete remediations:

          1. Regenerate the sidecar via ``sha256sum`` if the image is
             trusted (the common case after a golden rebuild).
          2. Uncheck the "VERIFY IMAGE INTEGRITY" toggle on Step 5 to
             bypass the check entirely (escape hatch).
        """
        msg = (
            f"SHA-256 mismatch on {role} image.\n\n"
            f"File:     {image_path.name}\n"
            f"Sidecar:  {sidecar_path.name}\n"
            f"Expected: {expected_hex[:16]}…\n"
            f"Computed: {computed_hex[:16]}…\n\n"
            f"Either the sidecar is stale (regenerate via "
            f"`sha256sum {image_path.name} > {sidecar_path.name}`) "
            f"or the image was modified/corrupted in transfer. "
            f"To bypass this check entirely, uncheck "
            f"'\U0001f6e1 VERIFY IMAGE INTEGRITY' on Step 5."
        )
        self._pending_verify_job = None
        self._pending_verify_roles = []
        self._status = "error"
        self._error_message = msg
        self.statusChanged.emit()
        self.errorMessageChanged.emit()

    @Slot()
    def cancel(self) -> None:
        """Request cancellation of the current verify / flash phase.

        The status flips to ``cancelling`` immediately so the operator gets
        instant feedback; the worker finish handler transitions to
        ``cancelled`` once the in-flight chunk completes.
        """
        if self._status not in ("verifying", "flashing"):
            return  # nothing to cancel
        self._user_cancelled = True
        self._cancel_event.set()
        if self._worker is not None and hasattr(self._worker._job, "cancel_event"):
            with contextlib.suppress(AttributeError):
                self._worker._job.cancel_event.set()
        self._status = "cancelling"
        self.statusChanged.emit()

    def _update_master(self, frac, phase, throughput_bps=0.0):
        self._master_progress = frac
        self._master_phase = phase
        self._master_throughput_bps = float(throughput_bps)
        self.masterProgressChanged.emit()
        self.masterPhaseChanged.emit()
        self.masterThroughputBpsChanged.emit()

    def _update_slave(self, frac, phase, throughput_bps=0.0):
        self._slave_progress = frac
        self._slave_phase = phase
        self._slave_throughput_bps = float(throughput_bps)
        self.slaveProgressChanged.emit()
        self.slavePhaseChanged.emit()
        self.slaveThroughputBpsChanged.emit()

    def _on_finished(self, ok, err):
        # Route an operator CANCEL (self._user_cancelled, set only by cancel())
        # to a clean "cancelled" state. We can't key off cancel_event here — it
        # also doubles as a thread-coordination signal, so a real write failure
        # would be mis-classified as a cancel.
        if self._user_cancelled:
            self._status = "cancelled"
            self._error_message = ""
        else:
            self._status = "done" if ok else "error"
            self._error_message = err
            if ok:
                # Completion flush: the throttle may have skipped the final
                # tick, so pin the bar(s) to 100% on success.
                self._master_progress = 1.0
                self._slave_progress = 1.0
                self.masterProgressChanged.emit()
                self.slaveProgressChanged.emit()
                # Advance the sequential role state machine (idempotent).
                if hasattr(self._wizard_state, "markCurrentRoleCompleted"):
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
            if not self._thread.wait(500):
                self._park_overrun_thread(self._thread, self._worker)
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


#: Default ``skip_verify`` for UI-built FlashJobs. Post-write SHA-256 readback
#: is reliable and ON by default.
_WINDOWS_SKIP_VERIFY = False


def _build_flash_job(wizard_state, platform_io=None):
    """Build a FlashJob from wizard_state fields for the current cycle.

    Sequential Deployment Assistant: each cycle flashes ONE role
    (master OR slave) — driven by ``wizard_state.currentRole``.

    Step 2 Config fields are NON-BLOCKING: empty strings on
    ``installUser`` / ``installPassword`` / ``hotspotPassword`` are
    silently substituted with the module-level ``DEFAULT_*`` constants
    above. This guarantees ``/boot/astromech_init.cfg`` is always
    complete on the SD card, no matter how the operator went through
    the wizard.

    The wlan0 bootstrap SSID comes from ``wizard_state.hotspotSsid`` — the
    single value minted once at wizard-state init and shared by both cards of
    a pair. A fresh one is generated locally only if a caller passes a wizard
    surface without the property (defensive).

    Returns None if construction fails because no platform IO is
    available (non-Windows host without an injected fake). Otherwise
    re-raises construction errors so the WRITE button never becomes a
    silent no-op. This function is module-level so it can be unit-tested
    with a fake wizard_state.
    """
    try:
        import sys
        if platform_io is None:
            if sys.platform == "win32":
                from astromechos_imager.platform.windows import WindowsPlatformIO
                platform_io = WindowsPlatformIO()
            else:
                return None

        from astromechos_imager.core.keygen import (
            generate_ed25519,
            generate_hotspot_ssid,
            generate_linux_account,
            load_persisted_pair,
            save_persisted_hotspot,
            save_persisted_pair,
        )
        from astromechos_imager.core.models import FirstbootConfig, Role
        from astromechos_imager.core.orchestrator import FlashJob

        # Zero-Touch: no user-pasted keys, ever. The Master↔Slave pair is
        # auto-generated and persisted in %APPDATA% — reusing the same pair
        # across runs lets the operator re-flash the Master alone without
        # invalidating the existing Slave's authorized_keys.
        existing = load_persisted_pair()
        ed25519 = existing if existing is not None else generate_ed25519()
        if existing is None:
            # First run — persist the freshly-generated pair so future flashes
            # (the master and slave cycles) reuse the same keys and keep the
            # pair symmetric across cards.
            save_persisted_pair(ed25519)

        # Non-blocking fallback: empty UI fields trigger the module-level
        # DEFAULT_* substitution. Operator-supplied values WIN; blank
        # values get the safe defaults (astromech / astropass). This
        # guarantees ``[hotspot]`` and ``[system]`` blocks in
        # ``/boot/astromech_init.cfg`` are always complete and ≥8 chars
        # (no firstboot brick-skip on the Pi).
        # Username is a FIXED system constant — the Golden's standardized
        # UID-1000 login that AstromechOS is pre-configured for. It is NOT
        # operator-editable (the wizard field is read-only) and the backend
        # IGNORES any wizard value, so the flashed account name can never
        # drift from the name cloud-init's chpasswd must target. Only the
        # PASSWORD is dynamic.
        install_user     = DEFAULT_INSTALL_USER
        install_password = (wizard_state.installPassword or "")         or DEFAULT_INSTALL_PASSWORD
        hotspot_psk      = (wizard_state.hotspotPassword or "")         or DEFAULT_HOTSPOT_PASSWORD

        linux_account = generate_linux_account(install_user, install_password)

        # wlan0 bootstrap SSID: the single early-generated value owned by
        # wizard_state (wizardState.hotspotSsid — minted at init, regenerated
        # per deployment on endSession). Both Master and Slave of a pair
        # inherit the SAME SSID so the runtime rendezvous works; the PSK flows
        # independently from the operator field. Defensive fallback only if a
        # caller passes a wizard surface without the property.
        ssid = (getattr(wizard_state, "hotspotSsid", "") or "").strip()
        if not ssid:
            ssid = generate_hotspot_ssid()
        hotspot = HotspotBootstrap(ssid=ssid, password=hotspot_psk)
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
        #   * install_user is the fixed UID-1000 account name so firstboot's
        #     home-dir creation / role-marker placement target the account
        #     cloud-init's chpasswd reconfigures.
        #   * The ed25519 keypair lives on the *job* (master_pair=), not on
        #     FirstbootConfig — that's the contract of FlashJob and what
        #     FirstbootBundle consumes.
        # imager_version / flashed_at_iso stamp provenance into the generated
        # /boot header.
        from astromechos_imager import __version__ as _imager_version
        from astromechos_imager.core.models import _utc_iso_now
        firstboot = FirstbootConfig(
            authorized_keys=[],
            install_user=install_user,
            hostname_master=wizard_state.hostnameMaster,
            hostname_slave=wizard_state.hostnameSlave,
            hotspot_bootstrap=hotspot,
            repo_url=wizard_state.repoUrl or None,
            wifi_ssid=wifi_ssid,
            wifi_psk=wifi_psk,
            imager_version=_imager_version,
            flashed_at_iso=_utc_iso_now(),
        )

        # Sequential workflow: one cycle = one role = one FlashJob. The
        # role is set on Screen 4 via wizard_state.setCurrentRole().
        current_role = (getattr(wizard_state, "currentRole", "") or "").strip()
        if current_role not in ("master", "slave"):
            raise RuntimeError(
                "Cannot build flash job: wizard_state.currentRole must be "
                f"'master' or 'slave' (got {current_role!r}). Screen 4 Role must run first."
            )

        drives = {d.physical_drive_id: d for d in platform_io.enumerate_removable_drives()}

        def _guard_target_is_not_source(drive, image_path_s: str) -> None:
            """SAFETY STOP: the target disk must never be the disk hosting
            the source image. The operator's USB SSD passes
            the removable-candidate filter (USB + under the 256 GiB cap);
            flashing it would destroy the very image being written. Degrades
            open: an unresolvable path blocks nothing."""
            ids_for = getattr(platform_io, "disk_ids_for_path", None)
            if ids_for is None or not image_path_s:
                return
            try:
                source_ids = set(ids_for(image_path_s))
            except Exception:
                return
            if drive.physical_drive_id in source_ids:
                raise RuntimeError(
                    f"SAFETY STOP: the selected target (disk "
                    f"{drive.physical_drive_id}, {drive.model}) is the disk "
                    f"that HOSTS the source image itself. Flashing it would "
                    f"destroy the image being written. Select the SD card, "
                    f"not the image drive."
                )

        if current_role == "master":
            drive = drives.get(wizard_state.masterDriveId)
            if drive is None:
                raise RuntimeError(
                    f"master drive id={wizard_state.masterDriveId} not found "
                    f"(was it removed since Step 3?)"
                )
            _guard_target_is_not_source(drive, wizard_state.masterImagePath)
            return FlashJob(
                platform_io=platform_io,
                image_path=Path(wizard_state.masterImagePath),
                target=drive,
                role=Role.MASTER,
                firstboot_config=firstboot,
                master_pair=ed25519,
                linux_account=linux_account,
                skip_verify=_WINDOWS_SKIP_VERIFY,
            )
        # current_role == "slave"
        drive = drives.get(wizard_state.slaveDriveId)
        if drive is None:
            raise RuntimeError(
                f"slave drive id={wizard_state.slaveDriveId} not found "
                f"(was it removed since Step 3?)"
            )
        _guard_target_is_not_source(drive, wizard_state.slaveImagePath)
        return FlashJob(
            platform_io=platform_io,
            image_path=Path(wizard_state.slaveImagePath),
            target=drive,
            role=Role.SLAVE,
            firstboot_config=firstboot,
            master_pair=ed25519,
            linux_account=linux_account,
            skip_verify=_WINDOWS_SKIP_VERIFY,
        )
    except Exception:
        # Re-raise so startFromWizard surfaces the failure in the UI instead of
        # leaving WRITE a silent no-op.
        raise
