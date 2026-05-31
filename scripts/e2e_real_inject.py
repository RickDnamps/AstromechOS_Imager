"""Real injection test on SD card I:\\ — Master then Slave cycle.

What this does (no admin required):
  1. Wipe everything on I:\\ except System Volume Information
  2. Apply FirstbootBundle.write_to(DriveLetterBootPartition('I'), Role.MASTER)
     with synthetic Step 4 credentials + a session-scoped hotspot SSID
  3. Validate the produced files match the expected contract:
       - /astromech_secrets/init_config.json   ← role + hostname
       - /astromech_secrets/authorized_keys    ← non-empty for slave only,
                                                  master pub for slave
       - /astromech_secrets/id_ed25519         ← MASTER only
       - /astromech_secrets/id_ed25519.pub     ← MASTER only
       - /astromech_init.cfg                   ← INI [system] / [hotspot]
       - /astromech_wlan.conf                  ← INI [home_wifi] (Wi-Fi set)
       - /ASTROMECH_FIRSTBOOT_READY            ← trigger marker, LAST
  4. Re-wipe + repeat as SLAVE
  5. Side-by-side report

What this does NOT do (would require admin):
  - Raw block write of the .img.gz to PHYSICALDRIVE7 (lock_and_dismount)
  - Rootfs personalization on the ext4 partition (libext2fs / debugfs)
  - /cmdline.txt resize-init injection (the FAT32 boot partition on a
    real flashed SD already contains the Pi-OS cmdline.txt; we don't
    have one here so we skip)

The injection logic (FirstbootBundle.write_to) is THE SAME code path
that runs after the raw block write completes in production. Validating
it on the existing I:\\ mount = validating the operator-visible artefacts
that the live Pi firstboot_setup.sh consumes verbatim.

Run:
    .venv\\Scripts\\python.exe scripts\\e2e_real_inject.py

Output:
    screenshots/e2e_audit/REAL_INJECT_REPORT.md
"""
from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.core.bootpartition import DriveLetterBootPartition
from astromechos_imager.core.customization import FirstbootBundle
from astromechos_imager.core.keygen import (
    generate_ed25519,
    generate_hotspot_bootstrap,
    generate_linux_account,
)
from astromechos_imager.core.models import FirstbootConfig, Role, _utc_iso_now

OUT = Path(__file__).resolve().parents[1] / "screenshots" / "e2e_audit"
OUT.mkdir(parents=True, exist_ok=True)
REPORT_PATH = OUT / "REAL_INJECT_REPORT.md"

# Synthetic test inputs (mirrors Eric's brief)
SYNTH = dict(
    install_user="testuser",
    install_password="TestPassword456",
    wifi_ssid="Test_Robot_Net",
    wifi_psk="TestPassword123",
    hotspot_psk="TestPassword123",
    hostname_master="astromech-master",
    hostname_slave="astromech-slave",
)

DRIVE = "I"
LINES: list[str] = []


def log(msg: str) -> None:
    print(msg)
    LINES.append(msg)


def wipe_drive(letter: str) -> None:
    """Remove every file/directory on the SD root EXCEPT the Windows
    System Volume Information folder (which Windows protects and would
    silently fail). This is the "blank canvas" we'd see after a raw
    block write that just imaged a fresh Pi OS template."""
    root = Path(f"{letter}:/")
    log(f"\n=== Wiping {root} ===")
    for child in root.iterdir():
        if child.name == "System Volume Information":
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            log(f"  removed {child.name}")
        except Exception as e:
            log(f"  ⚠️ could not remove {child.name}: {e}")


def build_cfg(hotspot_bootstrap, *, with_wifi: bool) -> FirstbootConfig:
    """Compose a FirstbootConfig the way flash_view_model._build_flash_job
    would, applying the same non-blocking default substitution."""
    return FirstbootConfig(
        authorized_keys=[],
        install_user=SYNTH["install_user"],
        hostname_master=SYNTH["hostname_master"],
        hostname_slave=SYNTH["hostname_slave"],
        hotspot_bootstrap=hotspot_bootstrap,
        wifi_ssid=SYNTH["wifi_ssid"] if with_wifi else None,
        wifi_psk=SYNTH["wifi_psk"] if with_wifi else None,
        imager_version="0.1.0",
        flashed_at_iso=_utc_iso_now(),
    )


def inject_role(role: Role, master_pair, hotspot_bootstrap) -> dict:
    """Apply FirstbootBundle.write_to for the given role on I:\\.
    Returns the BootPartition for post-validation."""
    role_label = role.value.upper()
    log(f"\n=== Injecting {role_label} role on I:\\ ===")
    wipe_drive(DRIVE)

    bp = DriveLetterBootPartition(DRIVE)
    cfg = build_cfg(hotspot_bootstrap, with_wifi=True)
    bundle = FirstbootBundle(cfg, master_pair)
    bundle.write_to(bp, role)
    log(f"  ✅ FirstbootBundle.write_to({role_label}) returned without error")
    return {"bp": bp, "cfg": cfg, "role": role}


def validate_role(state: dict) -> dict:
    """Verify the bundle's contract on the freshly-injected partition."""
    bp = state["bp"]
    cfg = state["cfg"]
    role = state["role"]
    role_label = role.value
    log(f"\n--- Validating {role_label.upper()} bundle ---")
    findings: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        glyph = "✅" if ok else "❌"
        log(f"  {glyph} {name}{(' — ' + detail) if detail else ''}")
        findings.append((name, ok, detail))

    # 1. Trigger marker present
    check("/ASTROMECH_FIRSTBOOT_READY present", bp.exists("/ASTROMECH_FIRSTBOOT_READY"))

    # 2. Secrets directory
    check("/astromech_secrets/ exists", bp.exists("/astromech_secrets"))

    # 3. init_config.json
    if bp.exists("/astromech_secrets/init_config.json"):
        obj = json.loads(bp.read_bytes("/astromech_secrets/init_config.json"))
        check("init_config.json role correct", obj.get("role") == role_label, f"got role={obj.get('role')!r}")
        expected_host = SYNTH["hostname_master"] if role is Role.MASTER else SYNTH["hostname_slave"]
        check("init_config.json hostname correct", obj.get("hostname") == expected_host, f"got {obj.get('hostname')!r}")
    else:
        check("init_config.json present", False, "FILE MISSING")

    # 4. authorized_keys — empty for master (Zero-Touch), master pub for slave
    if bp.exists("/astromech_secrets/authorized_keys"):
        keys_raw = bp.read_bytes("/astromech_secrets/authorized_keys").decode("utf-8").strip()
        if role is Role.MASTER:
            check("authorized_keys empty on Master (Zero-Touch)", keys_raw == "")
        else:
            check("authorized_keys contains Master pubkey", "ssh-ed25519" in keys_raw, f"first 60 chars: {keys_raw[:60]!r}")
    else:
        check("authorized_keys present", False, "FILE MISSING")

    # 5. Master keypair files (Master only)
    if role is Role.MASTER:
        priv_ok = bp.exists("/astromech_secrets/id_ed25519")
        pub_ok = bp.exists("/astromech_secrets/id_ed25519.pub")
        check("Master id_ed25519 (private) present", priv_ok)
        check("Master id_ed25519.pub present", pub_ok)
        if priv_ok:
            priv = bp.read_bytes("/astromech_secrets/id_ed25519")
            check("id_ed25519 has OpenSSH PEM header", priv.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----"))
    else:
        # Slave must NOT carry the private key
        check("Slave does NOT carry id_ed25519 private", not bp.exists("/astromech_secrets/id_ed25519"))

    # 6. astromech_init.cfg
    if bp.exists("/astromech_init.cfg"):
        cfg_text = bp.read_bytes("/astromech_init.cfg").decode("utf-8")
        check("init.cfg has [system] section", "[system]" in cfg_text)
        check("init.cfg [system] user = testuser", f"user = {SYNTH['install_user']}" in cfg_text)
        check("init.cfg has [hotspot] section", "[hotspot]" in cfg_text)
        check("init.cfg [hotspot] ssid line present", "ssid = Astromech-" in cfg_text)
        check("init.cfg [hotspot] password line present", f"password = {SYNTH['hotspot_psk']}" in cfg_text)
        check("init.cfg [hotspot] key_mgmt = wpa-psk", "key_mgmt = wpa-psk" in cfg_text)
    else:
        check("init.cfg present", False, "FILE MISSING")

    # 7. astromech_wlan.conf
    if bp.exists("/astromech_wlan.conf"):
        wlan_text = bp.read_bytes("/astromech_wlan.conf").decode("utf-8")
        check("wlan.conf has [home_wifi] section", "[home_wifi]" in wlan_text)
        check("wlan.conf ssid matches synthetic SSID", f"ssid = {SYNTH['wifi_ssid']}" in wlan_text)
        check("wlan.conf password matches synthetic PSK", f"password = {SYNTH['wifi_psk']}" in wlan_text)
        check("wlan.conf key_mgmt = wpa-psk", "key_mgmt = wpa-psk" in wlan_text)
    else:
        check("wlan.conf present", False, "FILE MISSING")

    passed = sum(1 for _, ok, _ in findings if ok)
    failed = sum(1 for _, ok, _ in findings if not ok)
    log(f"\n  Score: {passed} passed, {failed} failed (of {len(findings)})")
    return {"role": role_label, "findings": findings, "passed": passed, "failed": failed}


def main() -> int:
    log("# AstromechOS Imager — Real Injection Test on I:\\")
    log(f"\nGenerated: {_utc_iso_now()}")
    log(f"\nSynthetic inputs:")
    for k, v in SYNTH.items():
        log(f"  - {k} = {v!r}")

    # One session = one Ed25519 keypair + one hotspot bootstrap, shared
    # across both Master and Slave cards. The Slave's authorized_keys
    # is built from the Master's PUBLIC key (master_pair.public_openssh).
    master_pair = generate_ed25519()
    hotspot = generate_hotspot_bootstrap(SYNTH["hotspot_psk"])
    log(f"\nSession state:")
    log(f"  - ed25519 fingerprint: {master_pair.public_openssh.decode('ascii').strip()[:60]}...")
    log(f"  - hotspot SSID       : {hotspot.ssid}")

    # ── Master cycle ─────────────────────────────────────────────────
    master_state = inject_role(Role.MASTER, master_pair, hotspot)
    master_validation = validate_role(master_state)

    # Dump the final master directory listing for visual confirmation
    log("\n--- Master I:\\ contents post-injection ---")
    for p in sorted(Path("I:/").rglob("*")):
        if "System Volume" in str(p):
            continue
        rel = p.relative_to("I:/")
        marker = "DIR " if p.is_dir() else "FILE"
        size = "" if p.is_dir() else f"  ({p.stat().st_size} B)"
        log(f"  {marker}  {rel}{size}")

    # ── Slave cycle ──────────────────────────────────────────────────
    slave_state = inject_role(Role.SLAVE, master_pair, hotspot)
    slave_validation = validate_role(slave_state)

    log("\n--- Slave I:\\ contents post-injection ---")
    for p in sorted(Path("I:/").rglob("*")):
        if "System Volume" in str(p):
            continue
        rel = p.relative_to("I:/")
        marker = "DIR " if p.is_dir() else "FILE"
        size = "" if p.is_dir() else f"  ({p.stat().st_size} B)"
        log(f"  {marker}  {rel}{size}")

    # ── Summary ──────────────────────────────────────────────────────
    log("\n## Summary")
    log(f"  Master: {master_validation['passed']} passed, {master_validation['failed']} failed")
    log(f"  Slave : {slave_validation['passed']} passed, {slave_validation['failed']} failed")
    overall = master_validation["failed"] + slave_validation["failed"]
    if overall == 0:
        log("\n  🟢 OVERALL PASS — all customization invariants honoured")
    else:
        log(f"\n  🔴 {overall} validation failures — see per-role sections above")

    REPORT_PATH.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    log(f"\n📄 Report saved: {REPORT_PATH}")
    return 0 if overall == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
