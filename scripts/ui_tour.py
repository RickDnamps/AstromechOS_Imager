"""Capture one PNG per README walkthrough step into screenshots/.

Forces fake wizard state so the screens render with realistic content even
without SD cards / real images present. The live wizard is 7 steps —
1 Landing · 2 Config(Customize) · 3 Images · 4 Role · 5 Ops · 6 Cycle ·
7 Complete — but the README tells the story in a different order, so each
capture label below is paired with the wizard step (``goto`` index) whose
SCREEN it must show. Keep the two in sync if either changes.
Captures both Dark and Light themes back-to-back (sun/moon toggle wiring).
Run from project root:

    .venv\\Scripts\\python.exe scripts\\ui_tour.py

Output directory is gitignored (see .gitignore -> screenshots/).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QTimer

# Make the package importable when run as a loose script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.ui.app import build_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()

    # Seed realistic wizard state for the 7-step sequential wizard.
    # Use REAL AstromechOS images so Step 3 shows the genuine role-marker
    # validation badges (the path setters kick off the async validator). The
    # path shown is a CLEAN, release-style location (a local junction maps it
    # to the real files) so the published screenshot never leaks a personal
    # path. Falls back to a placeholder name on machines without the images.
    _rel = Path(r"C:\AstromechOS_Releases")
    _master_img = _rel / "AstromechOS_Master_11-06-2026.img.gz"
    _slave_img = _rel / "AstromechOS_Slave_11-06-2026.img.gz"
    state.setMasterImagePath(
        str(_master_img) if _master_img.exists()
        else r"C:\AstromechOS_Releases\AstromechOS_Master_11-06-2026.img.gz")
    state.setSlaveImagePath(
        str(_slave_img) if _slave_img.exists()
        else r"C:\AstromechOS_Releases\AstromechOS_Slave_11-06-2026.img.gz")
    # No fake drive ids are seeded: a live card is in the reader for the
    # Step-4 capture, and stale seed ids would mismatch its real id and leave
    # the card un-armed depending on auto-arm timing.
    state.setHostnameMaster("astromech-master")
    state.setHostnameSlave("astromech-slave")
    state.setRepoUrl("https://github.com/RickDnamps/AstromechOS")
    # Step 4 Customize — leave Robot Login + Hotspot blank so the
    # screenshot shows the empty-with-placeholder state a fresh operator
    # sees on first launch (placeholders read "astromech" / "astropass"
    # / "astropass" — the backend substitutes them at flash time via
    # the non-blocking fallback). Seed only the optional Wi-Fi pair so
    # the third card demonstrates a "filled" state too.
    state.setWifiSsid("HomeNetwork")
    state.setWifiPsk("hunter2024")

    # Splash auto-advances via a 1500 ms Timer inside main.qml — wait it
    # out for the step-1 capture instead of fighting it. For 2-6 we drive
    # navigation explicitly via WizardState.goto(). We capture each step
    # in dark mode, then re-walk in light mode.
    # 4th element = optional action to run after navigating, before capture.
    # (capture-label, goto-step, settle-ms, action). The label tracks the
    # README narrative; goto-step is the LIVE wizard step whose screen it shows.
    base_plan = [
        ("00-splash",          None, 2200, None),  # mid-loader (bar ~60%)
        ("01-landing",         None, 1800, None),  # step 1 — Landing
        ("02-customize",          2,  700, None),  # step 2 — Config (account/hotspot/wifi)
        ("03-images",             3, 7000, None),  # step 3 — Select Source Images (wait for role validation)
        ("04-target-drives",      4, 1200, None),  # step 4 — insert card + role + arm WRITE (live card)
        ("04b-write-confirm",     4,  900, "open_confirm"),  # ⚡ ERASE TARGET DRIVE? modal (Step 4)
        ("05-flashing",           5, 1000, "simulate_flash"),  # step 5 — Ops write stages (simulated)
        ("06-next-card",          6,  700, "flashed_master"),  # step 6 — Master done, insert next
        ("07-complete",           7,  700, "flashed_both"),    # step 7 — both done, deployment complete
    ]
    themes = ["dark", "light"]

    # Resolve the ThemeManager — exposed as a Python QObject via the
    # context, but also kept alive by build_app() on engine.themeManager.
    theme_mgr = getattr(engine, "themeManager", None)

    plan = []
    for theme_name in themes:
        for name, step, settle, action in base_plan:
            plan.append((f"{theme_name}/{name}", theme_name, step, settle, action))

    idx = {"i": 0}

    # FlashViewModel handle for the simulated "writing" capture. We push the
    # display state directly (status/phase/progress + change signals) so the
    # Ops screen renders mid-write WITHOUT ever calling startFromWizard() —
    # the tour never writes to the live card.
    flash_vm = engine.rootContext().contextProperty("flashViewModel")

    def _reset_flash():
        if flash_vm is None:
            return
        flash_vm._status = "idle"
        flash_vm._master_phase = ""
        flash_vm._master_progress = 0.0
        flash_vm._master_hash_progress = 0.0
        flash_vm._master_hash_sidecar_match = None
        flash_vm._master_throughput_bps = 0.0
        for sig in (
            flash_vm.statusChanged, flash_vm.masterPhaseChanged,
            flash_vm.masterProgressChanged, flash_vm.masterHashProgressChanged,
            flash_vm.masterHashSidecarMatchChanged,
            flash_vm.masterThroughputBpsChanged,
        ):
            sig.emit()

    def _simulate_master_flash():
        if flash_vm is None:
            return
        state.setCurrentRole("master")
        flash_vm._master_hash_progress = 1.0          # SHA-256 stage done
        flash_vm._master_hash_sidecar_match = True    # ✓ matches sidecar
        flash_vm._master_phase = "decompress_write"   # streaming stage active
        flash_vm._master_progress = 0.62
        flash_vm._master_throughput_bps = 18_500_000.0
        flash_vm._status = "flashing"
        for sig in (
            flash_vm.masterHashProgressChanged,
            flash_vm.masterHashSidecarMatchChanged,
            flash_vm.masterPhaseChanged, flash_vm.masterProgressChanged,
            flash_vm.masterThroughputBpsChanged, flash_vm.statusChanged,
        ):
            sig.emit()

    def _confirm_dialog():
        return window.findChild(QObject, "confirmDialog")

    def step():
        i = idx["i"]
        if i >= len(plan):
            app.quit()
            return
        name, theme_name, target_step, settle_ms, action = plan[i]
        if theme_mgr is not None:
            theme_mgr.setMode(theme_name)
        # Force the automount-defense banner OFF for captures. The tour runs
        # non-elevated, so mountvol /N fails and the worker flips the amber
        # "automount still ON" strip on — but the shipped app runs elevated
        # and never shows it. Keep screenshots representative of the real run.
        _ss = getattr(engine, "systemStatus", None)
        if _ss is not None:
            _ss.setAutomountDefenseActive(True)
        # Close any lingering modal confirm dialog from a previous capture
        # before navigating (it belongs to the Step 4 page being left).
        dlg = _confirm_dialog()
        if dlg is not None:
            QMetaObject.invokeMethod(dlg, "close")
        # Reset wizard back to step 1 between themes so the splash logic
        # is consistent (and clear the simulated flash progress).
        if name.endswith("00-splash") and i > 0:
            state.endSession()   # wipe completedRoles / cycle for a fresh pass
            state.goto(1)        # ensure fresh navigation surface
        # Simulate flash completion so the Cycle / Complete screens render
        # with the right "Master done" / "both done" state.
        if action == "flashed_master":
            state.setCurrentRole("master")
            state.markCurrentRoleCompleted()
        elif action == "flashed_both":
            for _r in ("master", "slave"):
                state.setCurrentRole(_r)
                state.markCurrentRoleCompleted()
        # Drive the simulated write state for the Ops capture; otherwise keep
        # the flash view-model idle so the Cycle/Complete screens and the
        # light-theme re-walk start clean (and quit isn't blocked by a fake
        # "flash busy" status).
        if action == "simulate_flash":
            _simulate_master_flash()
        else:
            _reset_flash()
        if target_step is not None:
            state.goto(target_step)
        # Grow the splash window to the wizard size before the Landing capture:
        # a real step change drives the resize, otherwise an early grab catches
        # the smaller splash-sized window (mismatched screenshot resolution).
        if name.endswith("01-landing"):
            state.goto(2)
            state.goto(1)
        # Arm the live card as MASTER for the Step-4 captures so both theme
        # passes render the same armed state (the rapid tour can reach Step 4
        # before the model's auto-arm settles on the real drive id).
        if target_step == 4:
            _dm = getattr(engine, "driveListModel", None)
            if _dm is not None and _dm.count >= 1:
                state.setCurrentRole("master")
                state.setMasterDriveId(_dm.firstDriveId)
        # Optional action: pop the ⚡ WRITE confirmation dialog open so we can
        # capture the "ERASE TARGET DRIVE?" warning the operator sees.
        if action == "open_confirm":
            def _open():
                d = _confirm_dialog()
                if d is not None:
                    QMetaObject.invokeMethod(d, "open")
            QTimer.singleShot(200, _open)
        QTimer.singleShot(settle_ms, lambda: capture(name))

    def capture(name: str):
        out = OUT / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        # Re-assert right before the grab: the non-elevated arming worker can
        # flip the banner back on during the settle delay (mountvol timeout).
        # A synchronous set here can't be raced before grabWindow().
        _ss = getattr(engine, "systemStatus", None)
        if _ss is not None:
            _ss.setAutomountDefenseActive(True)
        # Re-assert the armed card right before the Step-4 grabs too.
        if "04" in name:
            _dm = getattr(engine, "driveListModel", None)
            if _dm is not None and _dm.count >= 1:
                state.setCurrentRole("master")
                state.setMasterDriveId(_dm.firstDriveId)
        img = window.grabWindow()
        img.save(str(out))
        print(f"saved {out.relative_to(OUT.parent)}  ({img.width()}x{img.height()})")
        idx["i"] += 1
        QTimer.singleShot(80, step)

    QTimer.singleShot(150, step)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
