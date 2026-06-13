"""End-to-end READ-ONLY audit of the Imager wizard.

Captures all 7 wizard screens for both Master and Slave role cycles with
synthetic test credentials and the real images at J:/R2-D2_Build/images/.
Does NOT execute any destructive flash — that requires admin + operator
confirmation. Surfaces:
  * Drive enumeration whitelist (only removable drives shown)
  * Every screen of the wizard, both roles, both themes
  * Synthetic credential propagation
  * Pre-flash readiness checks

Output: screenshots/e2e_audit/screen<N>_<role>_<theme>.png
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

# Force UTF-8 stdout so emoji checkmarks land in the report file and the
# console without UnicodeEncodeError under Windows cp1252.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PySide6.QtCore import QTimer  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.platform.windows import WindowsPlatformIO  # noqa: E402
from astromechos_imager.ui.app import build_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "screenshots" / "e2e_audit"
OUT.mkdir(parents=True, exist_ok=True)

# Synthetic test credentials
SYNTH = {
    "linux_user": "testuser",
    "linux_pwd":  "TestPassword456",
    "wifi_ssid":  "Test_Robot_Net",
    "wifi_psk":   "TestPassword123",
    "hotspot_psk": "TestPassword123",   # reuse to make popup verification easier
}

IMG_DIR = Path(r"J:\R2-D2_Build\images")
MASTER_IMG = IMG_DIR / "AstromechOS_Master_31-05-2026.img.gz"
SLAVE_IMG  = IMG_DIR / "AstromechOS_Slave_31-05-2026.img.gz"

REPORT_LINES: list[str] = []


def log(msg: str) -> None:
    print(msg)
    REPORT_LINES.append(msg)


def audit_drive_enumeration() -> None:
    log("\n=== Drive whitelist audit ===")
    p = WindowsPlatformIO()
    drives = p.enumerate_removable_drives()
    if not drives:
        log("  ❌ NO drives returned by enumerate_removable_drives()")
        return
    for d in drives:
        letters = ",".join(d.drive_letters) or "(no letters)"
        log(f"  ✓ phys={d.physical_drive_id}  letters={letters}  size={d.size_bytes/1e9:.2f} GB  model={d.model}")
    only_removable = all("I" in d.drive_letters for d in drives)
    if only_removable and len(drives) == 1:
        log("  ✅ WHITELIST PASS — only drive I: is exposed (no fixed disks)")
    else:
        log("  ⚠️ unexpected enumeration — review listing above")


def audit_images() -> None:
    log("\n=== Image inventory ===")
    for label, p in (("MASTER", MASTER_IMG), ("SLAVE", SLAVE_IMG)):
        if not p.exists():
            log(f"  ❌ {label} image missing: {p}")
            continue
        size_mb = p.stat().st_size / (1 << 20)
        sidecar = p.with_suffix(p.suffix + ".sha256")
        sidecar_state = "MISSING"
        if sidecar.exists():
            sb = sidecar.stat().st_size
            sidecar_state = "EMPTY (0 B) — verify_integrity will FAIL" if sb == 0 else f"{sb} B"
        log(f"  ✓ {label}: {p.name} ({size_mb:.1f} MB) — sidecar: {sidecar_state}")


def main() -> int:
    audit_drive_enumeration()
    audit_images()

    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()
    theme_mgr = getattr(engine, "themeManager", None)
    _flash_vm = engine.rootContext().contextProperty("flashViewModel")

    # Seed synthetic config (Step 2 fields)
    state.setInstallUser(SYNTH["linux_user"])
    state.setInstallPassword(SYNTH["linux_pwd"])
    state.setWifiSsid(SYNTH["wifi_ssid"])
    state.setWifiPsk(SYNTH["wifi_psk"])
    state.setHotspotPassword(SYNTH["hotspot_psk"])
    state.setHostnameMaster("astromech-master")
    state.setHostnameSlave("astromech-slave")
    # Step 3 image paths
    state.setMasterImagePath(str(MASTER_IMG))
    state.setSlaveImagePath(str(SLAVE_IMG))
    # Real platform_io target — drive 7 = I:. Sequential workflow uses
    # the SAME physical drive for both cycles (single SD adapter is the
    # standard hardware setup); both roles may share one physical drive.
    state.setMasterDriveId(7)
    state.setSlaveDriveId(7)

    # Bootstrap SSID is minted at wizard-state init — read it directly.
    try:
        log(f"\n=== Session ===\n  hotspot SSID: {state.hotspotSsid}")
    except Exception as e:
        log(f"  ⚠️ could not read hotspotSsid: {e}")

    # Plan: 7 screens × 2 themes = 14 captures
    # For role-dependent screens (5 Flash, 6 NextCard) we capture once
    # per role (master / slave). Role is set BEFORE the goto so the
    # Step5/Step6 QML renders the right copy.
    plan: list[tuple[str, int, str, str]] = []
    # name                step  role        theme
    for theme in ("light", "dark"):
        for step in (1, 2, 3, 4):
            plan.append((f"step{step}", step, "master", theme))
        plan.append(("step5_master", 5, "master", theme))
        plan.append(("step6_master", 6, "master", theme))
        plan.append(("step5_slave",  5, "slave",  theme))
        plan.append(("step6_slave",  6, "slave",  theme))
        plan.append(("step7",        7, "master", theme))

    idx = {"i": 0}

    def next_step():
        i = idx["i"]
        if i >= len(plan):
            # Dump report and quit
            report_path = OUT / "AUDIT_REPORT.md"
            report_path.write_text("\n".join(REPORT_LINES) + "\n", encoding="utf-8")
            log(f"\n📄 Report saved: {report_path}")
            app.quit()
            return
        name, step, role, theme = plan[i]
        if theme_mgr:
            theme_mgr.setMode(theme)
        if hasattr(state, "setCurrentRole"):
            state.setCurrentRole(role)
        state.goto(step)
        QTimer.singleShot(450, lambda: capture(name, theme))

    def capture(name: str, theme: str):
        out = OUT / f"{name}_{theme}.png"
        img = window.grabWindow()
        img.save(str(out))
        size_kb = out.stat().st_size // 1024
        print(f"  saved {out.relative_to(OUT.parent.parent)}  ({img.width()}x{img.height()}, {size_kb} KB)")
        idx["i"] += 1
        QTimer.singleShot(80, next_step)

    QTimer.singleShot(1700, next_step)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
