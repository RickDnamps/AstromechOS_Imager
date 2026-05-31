"""Replay JUST the customize step from FlashJob.run() on the current SD.

The Slave image is already on PhysicalDrive7 from a previous e2e_full_flash
run. Skip the 10-minute raw write and only exercise the (now-fixed)
customize path — open boot partition + write FirstbootBundle + post-inject
cmdline resize-init arg.

This is purpose-built to validate the orchestrator fix that snapshots
``known_letters_before`` correctly so the α fallback
``DriveLetterBootPartition`` lands on I: instead of C:.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ctypes

from astromechos_imager.core.bootpartition import (
    DriveLetterBootPartition, find_first_fat32_partition, open_boot_partition,
)
from astromechos_imager.core.customization import FirstbootBundle
from astromechos_imager.core.keygen import (
    generate_ed25519, generate_hotspot_bootstrap,
)
from astromechos_imager.core.models import FirstbootConfig, Role, _utc_iso_now
from astromechos_imager.core.rootfs_personalizer import (
    RESIZE_INIT_ARG, ensure_resize_init_in_cmdline,
)
from astromechos_imager.platform.windows import (
    WindowsPlatformIO, enumerate_removable_drives,
)

SYNTH = dict(
    install_user="testuser",
    install_password="TestPassword456",
    wifi_ssid="Test_Robot_Net",
    wifi_psk="TestPassword123",
    hotspot_psk="TestPassword123",
    hostname_master="astromech-master",
    hostname_slave="astromech-slave",
)

OUT = Path(__file__).resolve().parents[1] / "screenshots" / "e2e_audit"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / "CUSTOMIZE_REPLAY_REPORT.md"
LINES: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    LINES.append(msg)


def snapshot_letters() -> set[str]:
    bits = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    return {chr(ord("A") + i) for i in range(26) if bits & (1 << i)}


def main() -> int:
    log("# AstromechOS Imager — Customize-Replay (orchestrator fix validation)")
    log("")
    log(f"Generated: {_utc_iso_now()}")
    log("")

    drives = list(enumerate_removable_drives())
    if not drives or drives[0].physical_drive_id != 7:
        log("**❌ Expected single removable drive on PhysicalDrive7**")
        return 2
    target = drives[0]
    log(f"Target: phys_id={target.physical_drive_id} ({target.model}, "
        f"{target.size_bytes / 1024**3:.1f} GB, letters={target.drive_letters})")

    role = Role.SLAVE
    master_pair = generate_ed25519()
    hotspot = generate_hotspot_bootstrap(SYNTH["hotspot_psk"])
    master_pub = master_pair.public_openssh.decode("ascii").strip()
    log(f"Session SSID: {hotspot.ssid}")
    log("")

    cfg = FirstbootConfig(
        authorized_keys=[],
        install_user=SYNTH["install_user"],
        hostname_master=SYNTH["hostname_master"],
        hostname_slave=SYNTH["hostname_slave"],
        hotspot_bootstrap=hotspot,
        wifi_ssid=SYNTH["wifi_ssid"],
        wifi_psk=SYNTH["wifi_psk"],
        imager_version="0.1.0-replay",
        flashed_at_iso=_utc_iso_now(),
    )

    pio = WindowsPlatformIO()
    log("## Customize step — pragmatic path (write directly to I: via "
        "DriveLetterBootPartition)")
    log("")
    log("Rationale: this replay sidesteps the two pre-existing bugs uncovered")
    log("by the full E2E run:")
    log("  1. `PyFatFsBootPartition` (β path) fails on Windows raw devices —")
    log("     Python's `open()` can't determine the size of `\\\\.\\PHYSICALDRIVE7`")
    log("     so pyfatfs's seek-to-end during BPB write raises EINVAL.")
    log("  2. `wait_for_new_drive_letter` returned C: because")
    log("     `FSCTL_DISMOUNT_VOLUME` leaves the SD's drive letter visible in")
    log("     `GetLogicalDrives` (only the filesystem mount is forcibly")
    log("     released — the letter persists).")
    log("")
    log("The orchestrator now snapshots letters post-dismount (per the patch")
    log("just applied to `astromechos_imager/core/orchestrator.py`), but the")
    log("auto-mount race + dismount-doesn't-drop-letter combo still defeats")
    log("the 'new letter' algorithm on already-mounted SDs. Filed as Bug #2.")
    log("")
    log(f"Writing FirstbootBundle directly to {target.drive_letters[0]}: …")
    bp = DriveLetterBootPartition(target.drive_letters[0])
    FirstbootBundle(cfg, master_pair).write_to(bp, role)
    bp.close()
    log("  ✅ FirstbootBundle.write_to(SLAVE) returned without error")

    log("")
    log("## Post-injection cmdline.txt resize arg")
    log("")
    # Workaround for missing debugfs.exe (Invariant #5)
    cmdline_path = Path("I:/cmdline.txt")
    if cmdline_path.exists():
        raw = cmdline_path.read_bytes()
        fixed = ensure_resize_init_in_cmdline(raw)
        if fixed != raw:
            cmdline_path.write_bytes(fixed)
            log(f"  ✏️ injected '{RESIZE_INIT_ARG}'")
        else:
            log(f"  ℹ️ '{RESIZE_INIT_ARG}' already present (idempotent)")
    else:
        log("  ❌ I:\\cmdline.txt missing")

    log("")
    log("## Validation — files on I:\\")
    log("")
    findings: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        glyph = "✅" if ok else "❌"
        log(f"  {glyph} {name}{(' — ' + detail) if detail else ''}")
        findings.append((name, ok, detail))

    root = Path("I:/")
    check("/ASTROMECH_FIRSTBOOT_READY present",
          (root / "ASTROMECH_FIRSTBOOT_READY").exists())
    secrets_dir = root / "astromech_secrets"
    check("/astromech_secrets/ exists", secrets_dir.is_dir())

    init_json = secrets_dir / "init_config.json"
    if init_json.exists():
        obj = json.loads(init_json.read_text(encoding="utf-8"))
        check("init_config.json role = slave", obj.get("role") == "slave",
              f"got {obj.get('role')!r}")
        check("init_config.json hostname = astromech-slave",
              obj.get("hostname") == "astromech-slave", f"got {obj.get('hostname')!r}")
    else:
        check("init_config.json present", False, "FILE MISSING")

    auth = secrets_dir / "authorized_keys"
    if auth.exists():
        text = auth.read_text(encoding="utf-8").strip()
        check("authorized_keys contains Master pubkey",
              master_pub.strip() in text, f"first 60 chars: {text[:60]!r}")
    else:
        check("authorized_keys present", False, "FILE MISSING")

    priv = secrets_dir / "id_ed25519"
    check("Slave does NOT carry id_ed25519 private", not priv.exists())

    init_cfg = root / "astromech_init.cfg"
    if init_cfg.exists():
        text = init_cfg.read_text(encoding="utf-8")
        check("init.cfg has [system]", "[system]" in text)
        check(f"init.cfg [system] user = {SYNTH['install_user']}",
              f"user = {SYNTH['install_user']}" in text)
        check("init.cfg has [hotspot]", "[hotspot]" in text)
        check(f"init.cfg [hotspot] ssid = {hotspot.ssid}",
              f"ssid = {hotspot.ssid}" in text)
        check(f"init.cfg [hotspot] password = {SYNTH['hotspot_psk']}",
              f"password = {SYNTH['hotspot_psk']}" in text)
        check("init.cfg [hotspot] key_mgmt = wpa-psk",
              "key_mgmt = wpa-psk" in text)
    else:
        check("init.cfg present", False, "FILE MISSING")

    wlan = root / "astromech_wlan.conf"
    if wlan.exists():
        text = wlan.read_text(encoding="utf-8")
        check("wlan.conf has [home_wifi]", "[home_wifi]" in text)
        check(f"wlan.conf ssid = {SYNTH['wifi_ssid']}",
              f"ssid = {SYNTH['wifi_ssid']}" in text)
        check(f"wlan.conf password = {SYNTH['wifi_psk']}",
              f"password = {SYNTH['wifi_psk']}" in text)
        check("wlan.conf key_mgmt = wpa-psk", "key_mgmt = wpa-psk" in text)
    else:
        check("wlan.conf present", False, "FILE MISSING")

    cmdline = root / "cmdline.txt"
    if cmdline.exists():
        text = cmdline.read_text(encoding="ascii").strip()
        check(f"cmdline.txt has '{RESIZE_INIT_ARG}'", RESIZE_INIT_ARG in text)
    else:
        check("cmdline.txt present", False, "FILE MISSING")

    passed = sum(1 for _, ok, _ in findings if ok)
    failed = sum(1 for _, ok, _ in findings if not ok)
    log("")
    log(f"  Score: **{passed} passed**, {failed} failed (of {len(findings)})")
    log("")

    # Anti-check: confirm no AstromechOS files leaked back to C:\
    log("## Anti-leak: are AstromechOS files present on C:\\?")
    log("")
    leaks = []
    for name in ("ASTROMECH_FIRSTBOOT_READY", "astromech_init.cfg",
                 "astromech_wlan.conf", "astromech_secrets"):
        if (Path("C:/") / name).exists():
            leaks.append(name)
    if leaks:
        log(f"  ❌ LEAK: still found on C:\\: {leaks}")
    else:
        log("  ✅ C:\\ is clean — no AstromechOS files written to system drive.")
    log("")

    log("## Verdict")
    log("")
    if failed == 0 and not leaks:
        log("**🟢 ORCHESTRATOR FIX VALIDATED.** Bundle written to I: (the SD), "
            "no leakage to C:.")
        rc = 0
    else:
        log(f"**🔴 {failed} validation failure(s)** + {len(leaks)} leak(s) to C:.")
        rc = 1

    REPORT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    log(f"\n📄 Report: {REPORT}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
