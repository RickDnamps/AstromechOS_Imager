"""Wizard navigation state — a QObject exposed to QML as `wizardState`."""
from __future__ import annotations

import logging

from PySide6.QtCore import Property, QObject, Signal, Slot

from astromechos_imager.core.keygen import generate_hotspot_ssid


class WizardState(QObject):
    """Tracks the current wizard step (1–7) and exposes navigation slots.

    Sequential Deployment Assistant workflow:
        1 — Landing (Start Deployment — generates the session hotspot SSID)
        2 — Config (UID-1000 user + Wi-Fi + hotspot PSK + hostnames + repo)
        3 — Images (browse source .img/.xz/.gz/.zip per role)
        4 — Role (pick the role for this cycle: master or slave)
        5 — Ops (verify + flash one card)
        6 — Cycle (insert next card OR finish)
        7 — Complete (both roles flashed — recap)

    Role state machine: each cycle picks one ``currentRole`` (master or
    slave), the flash-done handler appends it to ``completedRoles`` and
    bumps ``cycleIndex``. ``proposedNextRole`` auto-suggests the remaining
    role for the next cycle. ``resetForNextCycle`` clears per-cycle drive
    selections + currentRole but preserves the session-scoped completion
    history so the hotspot SSID and operator-typed config carry through.

    SSH key handling is fully automatic (no user input required): the
    Imager generates a Master↔Slave keypair on each flash session, drops
    the private half on the Master's boot partition and the matching
    public half into the Slave's authorized_keys. PC↔Master access is
    handled at first login by the operator (password or own ssh-copy-id).

    Step 2 Config collects the deployment-mandatory fields per
    CLAUDE.md "Provisioning architecture":
      * ``installUser`` / ``installPassword`` → UID-1000 Linux account
        (set at first boot via /firstrun.sh).
      * ``wifiSsid`` / ``wifiPsk``            → wlan1 domestic Wi-Fi
        (live firstboot brings up NetworkManager with these creds).
    The wlan0 bootstrap AP SSID is minted ONCE at wizard-state init,
    exposed read-only as ``hotspotSsid`` (the single source of truth — the
    Landing/Config/Cycle screens all bind to it) and baked identically into
    both cards so the runtime master-slave handshake works. It is regenerated
    per deployment by ``endSession()`` (FLASH ANOTHER) and preserved across
    ``resetForNextCycle()`` (the second card of a pair).
    """
    currentStepChanged = Signal(int)
    masterImagePathChanged = Signal(str)
    slaveImagePathChanged = Signal(str)
    masterDriveIdChanged = Signal(int)
    slaveDriveIdChanged = Signal(int)
    hostnameMasterChanged = Signal(str)
    hostnameSlaveChanged = Signal(str)
    repoUrlChanged = Signal(str)
    wifiSsidChanged = Signal(str)
    wifiPskChanged = Signal(str)
    # Step 4 Customize — UID-1000 Linux account credentials
    installUserChanged = Signal(str)
    installPasswordChanged = Signal(str)
    # Step 4 Customize — wlan0 private interconnect bootstrap PSK
    # (operator-supplied; SSID is auto-generated per burn by the Imager).
    hotspotPasswordChanged = Signal(str)
    # wlan0 bootstrap SSID — minted once at init, read-only in the UI,
    # regenerated per deployment on endSession(). Single source of truth.
    hotspotSsidChanged = Signal(str)

    # Image role validation (async — driven by image_validator)
    # status values: "none" | "checking" | "ok" | "mismatch"
    #              | "unknown_marker_absent" (soft pass, no marker found)
    masterImageRoleStatusChanged = Signal(str)
    slaveImageRoleStatusChanged = Signal(str)
    masterFilenameHintChanged = Signal(str)
    slaveFilenameHintChanged = Signal(str)
    # Internal queue-back signal — fired from the role-check daemon thread,
    # auto-marshalled by Qt onto the main thread. The third argument is a
    # generation token (audit High #12 / Medium #27): if the operator
    # re-picks an image while the previous check is still hashing, the
    # stale verdict carries an older token and is dropped on arrival.
    _roleStatusUpdated = Signal(str, str, int)   # role, status, generation

    # Integrity (SHA-256) toggle for Step 4
    verifyIntegrityChanged = Signal(bool)

    # Sequential Deployment Assistant state machine (replaces the deleted
    # MODE picker). cycleIndex bumps once per successful flash, completed
    # roles accumulate, currentRole names which role this cycle flashes,
    # and proposedNextRole derives from completedRoles for Screen 4.
    cycleIndexChanged = Signal(int)
    completedRolesChanged = Signal()
    currentRoleChanged = Signal(str)

    MIN_STEP = 1
    MAX_STEP = 7

    SUPPORTED_IMAGE_EXTENSIONS = (".img", ".xz", ".gz", ".zip")  # .img.xz, .img.gz handled by stem-check

    _VALID_ROLES = ("master", "slave")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # NOTE (WP6): the former ``release_disk_letters`` hook is gone. Drive
        # letters are now stripped for ALL non-suspect candidates at drive-
        # model bring-up (ui/app.py) — selection is a pure state write again,
        # with no hardware side effect. That also kills the audit R1 race
        # (selection daemon thread vs flash-time lock_and_dismount): the
        # flash-time live-letter merge + _wait_for_unmount gate remain the
        # backstops for anything still lettered (e.g. an explicitly-confirmed
        # suspect FIXED disk).
        self._step = self.MIN_STEP
        self._master_image_path = ""
        self._slave_image_path = ""
        self._master_drive_id = -1
        self._slave_drive_id = -1
        self._hostname_master = "astromech-master"
        self._hostname_slave = "astromech-slave"
        self._repo_url = ""
        # Sequential workflow state machine. Empty/zero values mean the
        # operator hasn't started any cycle yet — Screen 4 will offer a
        # free role pick. After the first successful flash, markCurrent-
        # RoleCompleted appends to _completed_roles and proposedNextRole
        # auto-suggests the remaining one.
        self._cycle_index: int = 0
        self._completed_roles: list[str] = []   # "master" and/or "slave" in completion order
        self._current_role: str = ""            # "master" | "slave" — what this cycle flashes
        self._wifi_ssid = ""
        self._wifi_psk = ""
        # Step 4 Customize — fields start EMPTY in the UI; the operator
        # can type custom values OR leave them blank. The non-blocking
        # fallback to "astromech" / "astropass" / "astropass" lives in
        # ``flash_view_model._build_flash_job`` (single source of truth)
        # so blank fields never reach the Pi side as empty strings. See
        # ``DEFAULT_INSTALL_USER`` etc. in flash_view_model.py.
        self._install_user = ""
        self._install_password = ""
        self._hotspot_password = ""
        # wlan0 bootstrap SSID — minted EARLY (here, at construction) so it is
        # available read-only on every screen long before any flash. Same
        # value baked into both cards of a pair; regenerated by endSession().
        self._hotspot_ssid = generate_hotspot_ssid()
        # Image validation
        self._master_image_role_status = "none"
        self._slave_image_role_status = "none"
        self._master_filename_hint = ""
        self._slave_filename_hint = ""
        self._verify_integrity = True   # zero-touch security default
        # Audit High #12 / Medium #27: generation token per role so the
        # last-write-wins race between rapidly-changed image selections
        # can't deliver a stale verdict.
        self._role_check_gens: dict[str, int] = {"master": 0, "slave": 0}
        # Audit High #13: shutdown flag set on aboutToQuit so daemon
        # threads stop emitting signals to a soon-to-be-destroyed
        # QObject. Best-effort: a thread already past the check will
        # still attempt one emit, but Qt drops queued signals to dead
        # receivers safely.
        self._shutting_down = False
        try:
            from PySide6.QtCore import QCoreApplication
            inst = QCoreApplication.instance()
            if inst is not None:
                inst.aboutToQuit.connect(self._on_about_to_quit)
        except Exception:
            pass  # never let setup wiring crash the constructor
        # Marshal worker-thread results back to the main loop. Qt picks
        # Qt.AutoConnection, which becomes QueuedConnection for inter-
        # thread signals — exactly what we want.
        self._roleStatusUpdated.connect(self._apply_role_status)

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
    # Step 3 — Image paths
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
            self._kick_role_check("master", p)

    @Slot(str)
    def setSlaveImagePath(self, p: str) -> None:
        p = self._normalize_path(p)
        if p != self._slave_image_path:
            self._slave_image_path = p
            self.slaveImagePathChanged.emit(p)
            self._kick_role_check("slave", p)

    # ── Role validation (async) ───────────────────────────────────────
    #
    # filename hint is computed synchronously (cheap regex) and the FAT32
    # marker read is delegated to a daemon thread because it needs to
    # decompress 128 MB of .img.xz — ~1-2 s on a modern CPU, too slow for
    # the FileDialog onAccepted callback.

    @Slot()
    def _on_about_to_quit(self) -> None:
        """Stop accepting role-check results so daemon threads can't emit
        on a QObject that the C++ side is about to destroy."""
        self._shutting_down = True

    def _kick_role_check(self, role_str: str, path: str) -> None:
        """Schedule asynchronous role verification on a daemon thread.

        Operator-facing policy (see CLAUDE.md / Step 2 UI):
          * marker says the right role            → "ok"
          * marker says the wrong role / wrong project / malformed
                                                  → "mismatch" (hard block)
          * no marker at all + filename agrees    → "unknown_marker_absent" (amber)
          * no marker + filename disagrees        → "mismatch" (hard block)
          * no marker + no filename hint          → "unknown_marker_absent" (amber)
          * decompression / pyfatfs / I/O failure → "check_failed" (hard block,
                                                    audit Low #46 — internal
                                                    errors must not be
                                                    silently soft-passed)

        Each invocation bumps the per-role generation counter; the daemon
        thread captures the token and the queued-back ``_apply_role_status``
        drops verdicts whose token is no longer current.
        """
        import threading as _threading
        from pathlib import Path as _Path

        from astromechos_imager.core.errors import (
            MalformedRoleMarkerError,
            MissingRoleMarkerError,
            RoleMismatchError,
            WrongProjectMarkerError,
        )
        from astromechos_imager.core.image_validator import (
            guess_role_from_filename,
            validate_image_role,
        )
        from astromechos_imager.core.models import Role

        # Bump the generation token FIRST so any in-flight worker that
        # completes after this call gets dropped on arrival.
        self._role_check_gens[role_str] += 1
        gen = self._role_check_gens[role_str]

        if not path:
            self._apply_role_status(role_str, "none", gen)
            self._apply_filename_hint(role_str, "")
            return
        p_obj = _Path(path)
        if not p_obj.is_file():
            self._apply_role_status(role_str, "none", gen)
            self._apply_filename_hint(role_str, "")
            return

        # Sync: filename hint (cheap regex).
        hint_role = guess_role_from_filename(p_obj.name)
        hint_str = hint_role.value if hint_role is not None else ""
        self._apply_filename_hint(role_str, hint_str)

        # Async: FAT32 marker read.
        self._apply_role_status(role_str, "checking", gen)
        expected = Role.MASTER if role_str == "master" else Role.SLAVE

        def _work() -> None:
            # Audit High #13: shortcut if shutdown is in progress.
            if self._shutting_down:
                return
            try:
                validate_image_role(p_obj, expected)
                status = "ok"
            except MissingRoleMarkerError:
                if hint_role is not None and hint_role != expected:
                    status = "mismatch"
                else:
                    status = "unknown_marker_absent"
            except (RoleMismatchError, WrongProjectMarkerError,
                    MalformedRoleMarkerError):
                status = "mismatch"
            except Exception:  # noqa: BLE001
                # Audit Low #46: pyfatfs ImportError, transient I/O, etc.
                # used to surface as the amber "unknown_marker_absent"
                # soft-pass which operators are documented to override.
                # That weakens the only role-safety gate before a
                # destructive write. Promote to "check_failed", a hard
                # block the UI flags red with a "see startup.log" hint.
                # Route through standard logging so the traceback lands in
                # the JSONL session log AND in startup.log (frozen builds).
                logging.getLogger(__name__).exception(
                    "role check failed for %s", p_obj.name
                )
                status = "check_failed"
            if not self._shutting_down:
                self._roleStatusUpdated.emit(role_str, status, gen)

        _threading.Thread(
            target=_work, daemon=True, name=f"role-check-{role_str}"
        ).start()

    def _apply_filename_hint(self, role: str, hint: str) -> None:
        if role == "master":
            if hint != self._master_filename_hint:
                self._master_filename_hint = hint
                self.masterFilenameHintChanged.emit(hint)
        else:
            if hint != self._slave_filename_hint:
                self._slave_filename_hint = hint
                self.slaveFilenameHintChanged.emit(hint)

    @Slot(str, str, int)
    def _apply_role_status(self, role: str, status: str, gen: int = 0) -> None:
        """Slot invoked on the main loop with the async verdict.

        ``gen`` is the generation token captured by the daemon when it
        started. If it no longer matches the current generation for this
        role, the operator has changed image since — drop the verdict.
        """
        if gen and gen != self._role_check_gens.get(role, 0):
            return   # stale verdict — newer check is in flight
        if role == "master":
            if status != self._master_image_role_status:
                self._master_image_role_status = status
                self.masterImageRoleStatusChanged.emit(status)
        else:
            if status != self._slave_image_role_status:
                self._slave_image_role_status = status
                self.slaveImageRoleStatusChanged.emit(status)

    # ── QML accessors for the validation state ────────────────────────

    @Property(str, notify=masterImageRoleStatusChanged)
    def masterImageRoleStatus(self) -> str:
        return self._master_image_role_status

    @Property(str, notify=slaveImageRoleStatusChanged)
    def slaveImageRoleStatus(self) -> str:
        return self._slave_image_role_status

    @Property(str, notify=masterFilenameHintChanged)
    def masterFilenameHint(self) -> str:
        return self._master_filename_hint

    @Property(str, notify=slaveFilenameHintChanged)
    def slaveFilenameHint(self) -> str:
        return self._slave_filename_hint

    @Property(bool, notify=verifyIntegrityChanged)
    def verifyIntegrity(self) -> bool:
        return self._verify_integrity

    @Slot(bool)
    def setVerifyIntegrity(self, v: bool) -> None:
        if v != self._verify_integrity:
            self._verify_integrity = v
            self.verifyIntegrityChanged.emit(v)

    @staticmethod
    def _normalize_path(p: str) -> str:
        """Strip file:// scheme and decode."""
        from urllib.parse import unquote, urlparse
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

    # ------------------------------------------------------------------
    # Step 3 — Storage / drive assignment
    # ------------------------------------------------------------------

    @Property(int, notify=masterDriveIdChanged)
    def masterDriveId(self) -> int:
        return self._master_drive_id

    @Property(int, notify=slaveDriveIdChanged)
    def slaveDriveId(self) -> int:
        return self._slave_drive_id

    # Note: the previous "cross-role collision check" (silently rejecting
    # setSlaveDriveId(X) when masterDriveId == X) was a legacy of the
    # deleted MODE_BOTH flow, which required two distinct drives written
    # in parallel. The sequential Deployment Assistant now flashes one
    # card per cycle and ``resetForNextCycle`` clears both ids between
    # cycles, so reusing the same drive (most common: a single SD
    # adapter) MUST be supported. Removing the cross-check also kills
    # the opaque "drive -1 (unplugged?)" UI symptom that bit Phase A
    # E2E audit Bug #2.
    @Slot(int)
    def setMasterDriveId(self, drive_id: int) -> None:
        if drive_id != self._master_drive_id:
            self._master_drive_id = drive_id
            self.masterDriveIdChanged.emit(drive_id)

    @Slot(int)
    def setSlaveDriveId(self, drive_id: int) -> None:
        if drive_id != self._slave_drive_id:
            self._slave_drive_id = drive_id
            self.slaveDriveIdChanged.emit(drive_id)

    # ------------------------------------------------------------------
    # Sequential workflow state machine (Screens 4 Role / 6 Cycle).
    # ------------------------------------------------------------------

    @Property(int, notify=cycleIndexChanged)
    def cycleIndex(self) -> int:
        return self._cycle_index

    @Property("QVariantList", notify=completedRolesChanged)
    def completedRoles(self) -> list[str]:
        return list(self._completed_roles)

    @Property(str, notify=currentRoleChanged)
    def currentRole(self) -> str:
        return self._current_role

    @Property(str, notify=completedRolesChanged)
    def proposedNextRole(self) -> str:
        """Auto-propose remaining role for Screen 4 Role pre-selection.

        Returns "" when:
          * nothing flashed yet — operator picks freely
          * both roles already flashed — no proposal
        """
        if not self._completed_roles:
            return ""  # nothing done yet — operator picks freely
        if "master" in self._completed_roles and "slave" not in self._completed_roles:
            return "slave"
        if "slave" in self._completed_roles and "master" not in self._completed_roles:
            return "master"
        return ""  # both done

    @Slot(str)
    def setCurrentRole(self, role: str) -> None:
        if role in self._VALID_ROLES and role != self._current_role:
            self._current_role = role
            self.currentRoleChanged.emit(self._current_role)

    @Slot()
    def markCurrentRoleCompleted(self) -> None:
        """Idempotent — called from the flash-done success path."""
        if not self._current_role or self._current_role in self._completed_roles:
            return
        self._completed_roles.append(self._current_role)
        self._cycle_index += 1
        self.completedRolesChanged.emit()
        self.cycleIndexChanged.emit(self._cycle_index)

    @Slot()
    def endSession(self) -> None:
        """Companion to FlashViewModel.endSession() — clears wizard
        cycle state for the next sequential deployment.

        Wired to Step 7 Complete 'FLASH ANOTHER' button (audit bugs C3
        + H1). resetForNextCycle() only clears per-cycle drive ids; a
        full session end must ALSO wipe completedRoles + cycleIndex so
        Step 4 doesn't show the "✓ DONE" badge on a brand-new card.
        """
        self._cycle_index = 0
        self._completed_roles.clear()
        self._current_role = ""
        self._master_drive_id = -1
        self._slave_drive_id = -1
        # Fresh deployment ⇒ fresh bootstrap SSID so the next pair doesn't
        # camp the previous robot's wlan0 rendezvous (collision-free per burn).
        self._hotspot_ssid = generate_hotspot_ssid()
        self.hotspotSsidChanged.emit(self._hotspot_ssid)
        self.cycleIndexChanged.emit(0)
        self.completedRolesChanged.emit()
        self.currentRoleChanged.emit("")
        self.masterDriveIdChanged.emit(-1)
        self.slaveDriveIdChanged.emit(-1)

    @Slot()
    def resetForNextCycle(self) -> None:
        """Called from Screen 6 'Insert next card' before looping to Step 4.

        Clears the per-cycle drive ids + currentRole, but preserves
        completedRoles / cycleIndex so proposedNextRole continues to drive
        Screen 4 pre-selection and the session-scoped hotspot SSID
        carries through to the next card.
        """
        self._current_role = ""
        self._master_drive_id = -1
        self._slave_drive_id = -1
        self.currentRoleChanged.emit(self._current_role)
        self.masterDriveIdChanged.emit(self._master_drive_id)
        self.slaveDriveIdChanged.emit(self._slave_drive_id)

    # ------------------------------------------------------------------
    # Defaults (hostnames / fork URL / Wi-Fi) — internal, no UI surface.
    # Kept as properties so future Settings panels can hook in without a
    # data-model change.
    # ------------------------------------------------------------------

    @Property(str, notify=hostnameMasterChanged)
    def hostnameMaster(self) -> str:
        return self._hostname_master

    @Slot(str)
    def setHostnameMaster(self, val: str) -> None:
        if val != self._hostname_master:
            self._hostname_master = val
            self.hostnameMasterChanged.emit(val)

    @Property(str, notify=hostnameSlaveChanged)
    def hostnameSlave(self) -> str:
        return self._hostname_slave

    @Slot(str)
    def setHostnameSlave(self, val: str) -> None:
        if val != self._hostname_slave:
            self._hostname_slave = val
            self.hostnameSlaveChanged.emit(val)

    @Property(str, notify=repoUrlChanged)
    def repoUrl(self) -> str:
        return self._repo_url

    @Slot(str)
    def setRepoUrl(self, val: str) -> None:
        if val != self._repo_url:
            self._repo_url = val
            self.repoUrlChanged.emit(val)

    # (reuseHotspot property removed — audit WP9: vestige of the deleted
    # MODE_BOTH flow; no QML binding, _build_flash_job never read it.)

    # ------------------------------------------------------------------
    # Wi-Fi (optional, wlan1 home network) — Phase 8.10
    # ------------------------------------------------------------------

    @Property(str, notify=wifiSsidChanged)
    def wifiSsid(self) -> str:
        return self._wifi_ssid

    @Slot(str)
    def setWifiSsid(self, v: str) -> None:
        if v != self._wifi_ssid:
            self._wifi_ssid = v
            self.wifiSsidChanged.emit(v)

    @Property(str, notify=wifiPskChanged)
    def wifiPsk(self) -> str:
        return self._wifi_psk

    @Slot(str)
    def setWifiPsk(self, v: str) -> None:
        if v != self._wifi_psk:
            self._wifi_psk = v
            self.wifiPskChanged.emit(v)

    # ------------------------------------------------------------------
    # Step 4 Customize — UID-1000 deployment account + dual-WLAN.
    # Fields are NON-BLOCKING: empty UI values trigger backend default
    # substitution in ``flash_view_model._build_flash_job`` (astromech
    # / astropass / astropass). Validators are still exposed as @Slot
    # so QML can render live ✓/✗ glyphs and gate the WRITE button on
    # the "non-empty AND invalid" case (operator-typed garbage), never
    # on the "empty" case (operator wants the default).
    # ------------------------------------------------------------------

    @Property(str, notify=installUserChanged)
    def installUser(self) -> str:
        return self._install_user

    @Slot(str)
    def setInstallUser(self, v: str) -> None:
        if v != self._install_user:
            self._install_user = v
            self.installUserChanged.emit(v)

    @Property(str, notify=installPasswordChanged)
    def installPassword(self) -> str:
        return self._install_password

    @Slot(str)
    def setInstallPassword(self, v: str) -> None:
        if v != self._install_password:
            self._install_password = v
            self.installPasswordChanged.emit(v)

    @Slot(str, result=bool)
    def isValidInstallUser(self, v: str) -> bool:
        """True iff ``v`` matches the POSIX login regex enforced by
        ``core/validators.validate_install_user`` (lowercase + digits +
        ``_-``, must start with letter or underscore, ≤32 chars)."""
        from astromechos_imager.core.validators import (
            InvalidInstallUserError,
            validate_install_user,
        )
        try:
            validate_install_user(v)
            return True
        except InvalidInstallUserError:
            return False

    @Slot(str, result=bool)
    def isValidInstallPassword(self, v: str) -> bool:
        """Minimum 8 ASCII-printable characters — the Pi's PAM defaults
        accept shorter, but 8 keeps SSH brute-force out of trivial range
        and matches the WPA2-PSK minimum. No newlines, no NULs."""
        if len(v) < 8:
            return False
        if not v.isascii() or not v.isprintable():
            return False
        return True

    @Slot(str, result=bool)
    def isValidWifiSsid(self, v: str) -> bool:
        """Domestic Wi-Fi SSID: 1-32 UTF-8 bytes, no control chars."""
        if not v:
            return False
        if len(v.encode("utf-8")) > 32:
            return False
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in v):
            return False
        return True

    @Slot(str, result=bool)
    def isValidWifiPsk(self, v: str) -> bool:
        """WPA2-PSK: 8-63 ASCII printable characters per IEEE 802.11."""
        if not (8 <= len(v) <= 63):
            return False
        if not v.isascii() or not v.isprintable():
            return False
        return True

    @Property(str, notify=hotspotSsidChanged)
    def hotspotSsid(self) -> str:
        """Read-only wlan0 bootstrap SSID (``Astromech-XXXX``), the single
        source of truth bound by Landing / Config / Cycle screens. Minted at
        construction; regenerated only by ``endSession()``."""
        return self._hotspot_ssid

    @Property(str, notify=hotspotPasswordChanged)
    def hotspotPassword(self) -> str:
        return self._hotspot_password

    @Slot(str)
    def setHotspotPassword(self, v: str) -> None:
        if v != self._hotspot_password:
            self._hotspot_password = v
            self.hotspotPasswordChanged.emit(v)

    @Slot(str, result=bool)
    def isValidHotspotPassword(self, v: str) -> bool:
        """Bootstrap PSK shares WPA2-PSK constraints (8-63 ASCII
        printable). Required: the auto-generated SSID is not enough on
        its own — without a PSK the AP would be open and a workshop
        neighbour could trivially camp the FINAL per-robot SSID once
        the runtime handover rotates to it (PSK carries through)."""
        return self.isValidWifiPsk(v)
