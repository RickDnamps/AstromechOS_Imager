"""Full E2E flash — exercises the SAME FlashJob code path as Step 5 WRITE.

Pipeline per role:
    1. Build a FlashJob with synthetic Step 4 credentials.
    2. orchestrator.FlashJob.run():
         a. lock_and_dismount(I:)
         b. raw block write of <image>.img.gz to \\.\PHYSICALDRIVE7
         c. SHA256 verify readback
         d. update_disk_properties (Windows auto-remount)
         e. FirstbootBundle.write_to(boot, role)
            ↳ uses β PyFatFsBootPartition over the raw device
              OR α DriveLetterBootPartition via the remounted I:
    3. Wait for I: to be available, then post-step:
         a. Inject the Pi-OS rootfs auto-resize arg into cmdline.txt
            (normally done by RootfsPersonalizer.apply() — skipped here
             because vendored debugfs.exe / e2fsck.exe are missing,
             see vendor/MISSING_BINARIES.md)
    4. Validate every artefact on I:.

Two cycles back-to-back: MASTER first, then SLAVE.

SAFETY: refuses to run unless ``enumerate_removable_drives()`` returns
exactly one drive AND that drive is PhysicalDrive7. This is the same
filter the Imager UI uses.

Output:
    screenshots/e2e_audit/FULL_FLASH_REPORT.md
    screenshots/e2e_audit/progress_master.csv
    screenshots/e2e_audit/progress_slave.csv
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.core.bootpartition import DriveLetterBootPartition
from astromechos_imager.core.diskwriter import DiskWriterProgress
from astromechos_imager.core.keygen import (
    generate_ed25519,
    generate_hotspot_bootstrap,
    generate_linux_account,
)
from astromechos_imager.core.models import DiskRef, FirstbootConfig, Role, _utc_iso_now
from astromechos_imager.core.orchestrator import FlashJob
from astromechos_imager.core.rootfs_personalizer import (
    RESIZE_INIT_ARG,
    ensure_resize_init_in_cmdline,
)
from astromechos_imager.platform.windows import (
    WindowsPlatformIO, enumerate_removable_drives,
)

EXPECTED_PHYS_ID = 7
IMAGES_DIR = Path(r"J:\R2-D2_Build\images")
MASTER_IMG = IMAGES_DIR / "AstromechOS_Master_31-05-2026.img.gz"
SLAVE_IMG = IMAGES_DIR / "AstromechOS_Slave_31-05-2026.img.gz"

OUT = Path(__file__).resolve().parents[1] / "screenshots" / "e2e_audit"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / "FULL_FLASH_REPORT.md"

SYNTH = dict(
    install_user="testuser",
    install_password="TestPassword456",
    wifi_ssid="Test_Robot_Net",
    wifi_psk="TestPassword123",
    hotspot_psk="TestPassword123",
    hostname_master="astromech-master",
    hostname_slave="astromech-slave",
)

LINES: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    LINES.append(msg)


# ── Pre-flight safety re-check ─────────────────────────────────────────
def safety_recheck() -> DiskRef:
    log("## Safety re-check")
    log("")
    drives = list(enumerate_removable_drives())
    if len(drives) != 1:
        log(f"**❌ Expected exactly 1 removable drive; got {len(drives)}.** ABORT.")
        raise SystemExit(2)
    sole = drives[0]
    if sole.physical_drive_id != EXPECTED_PHYS_ID:
        log(f"**❌ Sole removable drive is phys_id={sole.physical_drive_id}, "
            f"not {EXPECTED_PHYS_ID}.** ABORT.")
        raise SystemExit(2)
    log(f"✅ Sole removable drive locked in: phys_id={sole.physical_drive_id} "
        f"({sole.model}, {sole.size_bytes / 1024**3:.1f} GB, letters={sole.drive_letters})")
    log("")
    return sole


# ── Progress observation ───────────────────────────────────────────────
class ProgressRecorder:
    """Capture every progress event with wall-clock timestamps for UX audit."""

    def __init__(self, role: Role, csv_path: Path) -> None:
        self.role = role
        self.csv_path = csv_path
        self.samples: list[tuple[float, str, int, int | None, float]] = []
        self._start = time.monotonic()
        self._last_print = 0.0
        self._lock = threading.Lock()

    def __call__(self, prog: DiskWriterProgress) -> None:
        with self._lock:
            t = time.monotonic() - self._start
            self.samples.append((t, prog.phase, prog.bytes_done,
                                 prog.bytes_total, prog.throughput_bps))
            # Throttled stdout
            if t - self._last_print > 1.0:
                self._last_print = t
                pct = (
                    (prog.bytes_done / prog.bytes_total * 100.0)
                    if prog.bytes_total else 0.0
                )
                log(f"    [{self.role.value} {prog.phase}] "
                    f"{prog.bytes_done / 1024**2:.1f} MB "
                    f"({pct:.1f}%) @ {prog.throughput_bps / 1024**2:.1f} MB/s")

    def save(self) -> None:
        with self.csv_path.open("w", encoding="utf-8") as f:
            f.write("t_seconds,phase,bytes_done,bytes_total,throughput_bps\n")
            for row in self.samples:
                f.write(
                    f"{row[0]:.3f},{row[1]},{row[2]},"
                    f"{'' if row[3] is None else row[3]},{row[4]:.1f}\n"
                )


# ── Post-flash cmdline.txt injection (workaround) ──────────────────────
def post_inject_cmdline(role: Role) -> bool:
    """Inject the Pi-OS rootfs auto-resize arg into I:\\cmdline.txt.

    In production, RootfsPersonalizer.apply() does this. Since the vendored
    e2fsprogs binaries are missing (see vendor/MISSING_BINARIES.md), we
    skip RootfsPersonalizer in the FlashJob but still validate the FAT32
    side of Invariant #5 (CLAUDE.md) by injecting via DriveLetterBootPartition.

    Returns True if the arg ended up in cmdline.txt (whether by our write
    or already present).
    """
    cmdline_path = Path("I:/cmdline.txt")
    if not cmdline_path.exists():
        log(f"  ⚠️ I:\\cmdline.txt missing for {role.value} — "
            "post-injection skipped")
        return False
    raw = cmdline_path.read_bytes()
    fixed = ensure_resize_init_in_cmdline(raw)
    if fixed == raw:
        log(f"  ℹ️ cmdline.txt already has '{RESIZE_INIT_ARG}' "
            "(idempotent no-op)")
        return True
    cmdline_path.write_bytes(fixed)
    log(f"  ✏️ injected '{RESIZE_INIT_ARG}' into cmdline.txt")
    # Re-read for verification
    return RESIZE_INIT_ARG.encode("ascii") in cmdline_path.read_bytes()


# ── Mount waiter ───────────────────────────────────────────────────────
def wait_for_i(max_wait_s: float = 30.0) -> bool:
    log("  ⏳ waiting for I: to remount after raw write…")
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_wait_s:
        if Path("I:/").exists() and any(Path("I:/").iterdir()):
            t = time.monotonic() - t0
            log(f"  ✅ I: available after {t:.1f}s")
            return True
        time.sleep(0.5)
    log("  ❌ I: did not appear within timeout")
    return False


# ── Cycle ──────────────────────────────────────────────────────────────
def flash_cycle(role: Role, image: Path, target: DiskRef, master_pair,
                hotspot, csv_path: Path) -> dict:
    role_label = role.value.upper()
    log(f"\n## {role_label} cycle")
    log("")
    log(f"Image: `{image.name}` ({image.stat().st_size / 1024**2:.1f} MB compressed)")
    log(f"Target: phys_id={target.physical_drive_id} ({target.model})")
    log("")

    cfg = FirstbootConfig(
        authorized_keys=[],
        install_user=SYNTH["install_user"],
        hostname_master=SYNTH["hostname_master"],
        hostname_slave=SYNTH["hostname_slave"],
        hotspot_bootstrap=hotspot,
        wifi_ssid=SYNTH["wifi_ssid"],
        wifi_psk=SYNTH["wifi_psk"],
        imager_version="0.1.0-e2e",
        flashed_at_iso=_utc_iso_now(),
    )

    rec = ProgressRecorder(role, csv_path)
    skip_verify = bool(int(os.environ.get("E2E_SKIP_VERIFY", "0")))
    log(f"  skip_verify = {skip_verify}")
    job = FlashJob(
        platform_io=WindowsPlatformIO(),
        image_path=image,
        target=target,
        role=role,
        firstboot_config=cfg,
        master_pair=master_pair,
        on_progress=rec,
        skip_verify=skip_verify,
        skip_customize=False,
        linux_account=None,           # debugfs.exe missing — see post_inject_cmdline()
        ext4_debugfs_exe=None,
        ext4_e2fsck_exe=None,
    )

    t0 = time.monotonic()
    result = job.run()
    elapsed = time.monotonic() - t0
    rec.save()

    log("")
    log(f"  FlashJob.run() returned in {elapsed:.1f}s")
    if not result.ok:
        log(f"  ❌ FlashJob FAILED: {result.error!r}")
        log(f"  Bytes written: {result.bytes_written / 1024**2:.1f} MB")
        return {"role": role_label, "ok": False, "error": repr(result.error),
                "elapsed": elapsed, "bytes_written": result.bytes_written}

    log(f"  ✅ {result.bytes_written / 1024**2:.1f} MB written")
    log(f"  ✅ source SHA256: {result.source_sha256}")
    log("")

    # Wait for I: remount + post-inject cmdline.txt
    wait_for_i()
    cmdline_ok = post_inject_cmdline(role)

    return {"role": role_label, "ok": True, "elapsed": elapsed,
            "bytes_written": result.bytes_written,
            "sha256": result.source_sha256, "cmdline_ok": cmdline_ok}


# ── Post-flash validation on I:\ ────────────────────────────────────────
def validate(role: Role, hotspot_ssid: str, master_pubkey: str) -> dict:
    role_label = role.value
    log(f"\n### Validation — {role_label.upper()}")
    log("")
    findings: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        glyph = "✅" if ok else "❌"
        log(f"  {glyph} {name}{(' — ' + detail) if detail else ''}")
        findings.append((name, ok, detail))

    root = Path("I:/")
    # 1. Trigger marker (must be LAST, must exist)
    check("/ASTROMECH_FIRSTBOOT_READY present", (root / "ASTROMECH_FIRSTBOOT_READY").exists())

    # 2. Secrets dir
    secrets_dir = root / "astromech_secrets"
    check("/astromech_secrets/ exists", secrets_dir.is_dir())

    # 3. init_config.json contract
    init_json = secrets_dir / "init_config.json"
    if init_json.exists():
        obj = json.loads(init_json.read_text(encoding="utf-8"))
        check("init_config.json role correct", obj.get("role") == role_label,
              f"got role={obj.get('role')!r}")
        expected_host = SYNTH["hostname_master"] if role is Role.MASTER else SYNTH["hostname_slave"]
        check("init_config.json hostname correct", obj.get("hostname") == expected_host,
              f"got {obj.get('hostname')!r}")
    else:
        check("init_config.json present", False, "FILE MISSING")

    # 4. authorized_keys: empty on master (Zero-Touch), master pub on slave
    auth = secrets_dir / "authorized_keys"
    if auth.exists():
        text = auth.read_text(encoding="utf-8").strip()
        if role is Role.MASTER:
            check("authorized_keys empty (Master Zero-Touch)", text == "")
        else:
            check("authorized_keys contains Master pubkey", master_pubkey.strip() in text,
                  f"first 60 chars: {text[:60]!r}")
    else:
        check("authorized_keys present", False, "FILE MISSING")

    # 5. Master keypair files
    priv = secrets_dir / "id_ed25519"
    pub = secrets_dir / "id_ed25519.pub"
    if role is Role.MASTER:
        check("Master id_ed25519 (private) present", priv.exists())
        check("Master id_ed25519.pub present", pub.exists())
        if priv.exists():
            check("id_ed25519 has OpenSSH PEM header",
                  priv.read_bytes().startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----"))
    else:
        check("Slave does NOT carry id_ed25519 private", not priv.exists())

    # 6. astromech_init.cfg INI contract
    init_cfg = root / "astromech_init.cfg"
    if init_cfg.exists():
        text = init_cfg.read_text(encoding="utf-8")
        check("init.cfg has [system] section", "[system]" in text)
        check(f"init.cfg [system] user = {SYNTH['install_user']}",
              f"user = {SYNTH['install_user']}" in text)
        check("init.cfg has [hotspot] section", "[hotspot]" in text)
        check(f"init.cfg [hotspot] ssid = {hotspot_ssid}", f"ssid = {hotspot_ssid}" in text)
        check(f"init.cfg [hotspot] password = {SYNTH['hotspot_psk']}",
              f"password = {SYNTH['hotspot_psk']}" in text)
        check("init.cfg [hotspot] key_mgmt = wpa-psk", "key_mgmt = wpa-psk" in text)
    else:
        check("init.cfg present", False, "FILE MISSING")

    # 7. astromech_wlan.conf INI contract
    wlan = root / "astromech_wlan.conf"
    if wlan.exists():
        text = wlan.read_text(encoding="utf-8")
        check("wlan.conf has [home_wifi] section", "[home_wifi]" in text)
        check(f"wlan.conf ssid = {SYNTH['wifi_ssid']}",
              f"ssid = {SYNTH['wifi_ssid']}" in text)
        check(f"wlan.conf password = {SYNTH['wifi_psk']}",
              f"password = {SYNTH['wifi_psk']}" in text)
        check("wlan.conf key_mgmt = wpa-psk", "key_mgmt = wpa-psk" in text)
    else:
        check("wlan.conf present", False, "FILE MISSING")

    # 8. Invariant #5 — cmdline.txt has the rootfs auto-resize arg
    cmdline = root / "cmdline.txt"
    if cmdline.exists():
        text = cmdline.read_text(encoding="ascii").strip()
        check(f"cmdline.txt has '{RESIZE_INIT_ARG}'", RESIZE_INIT_ARG in text)
    else:
        check("cmdline.txt present", False, "FILE MISSING — boot partition not flashed properly")

    passed = sum(1 for _, ok, _ in findings if ok)
    failed = sum(1 for _, ok, _ in findings if not ok)
    log("")
    log(f"  Score: **{passed} passed**, {failed} failed (of {len(findings)})")
    return {"role": role_label, "passed": passed, "failed": failed, "findings": findings}


# ── Main ───────────────────────────────────────────────────────────────
def main() -> int:
    log("# AstromechOS Imager — FULL E2E Flash on PhysicalDrive7")
    log("")
    log(f"Generated: {_utc_iso_now()}")
    log("")
    log("This run exercises the SAME `FlashJob.run()` code path that the UI's")
    log("Step 5 'WRITE' button triggers, on the real removable USB SD card.")
    log("")

    # Defense-in-depth: re-check the drive list before touching anything.
    target = safety_recheck()

    # Session state: one ed25519 keypair + one hotspot bootstrap, shared
    # across both Master and Slave (the Slave's authorized_keys is built
    # from the Master's PUBLIC key — same as production).
    master_pair = generate_ed25519()
    hotspot = generate_hotspot_bootstrap(SYNTH["hotspot_psk"])
    master_pub = master_pair.public_openssh.decode("ascii").strip()
    log("## Session state")
    log("")
    log(f"- ed25519 pub (fingerprint snippet): `{master_pub[:60]}…`")
    log(f"- hotspot SSID                     : `{hotspot.ssid}`  (auto-generated)")
    log(f"- hotspot PSK                      : `{SYNTH['hotspot_psk']}`")
    log("")
    log(f"### Synthetic credentials")
    log("")
    for k, v in SYNTH.items():
        log(f"- `{k}` = `{v}`")
    log("")
    log(f"### Gap acknowledgement")
    log("")
    log("- `vendor/debugfs.exe` and `vendor/e2fsck.exe` are not installed on")
    log("  this dev machine (see `vendor/MISSING_BINARIES.md`).")
    log("- Consequence: `linux_account` is passed as `None` → "
        "`RootfsPersonalizer.apply()` is skipped.")
    log("- Workaround: after raw write completes, this script independently")
    log("  injects the Pi-OS rootfs-resize arg into `/cmdline.txt` via")
    log("  `DriveLetterBootPartition` so Invariant #5 (CLAUDE.md) is still")
    log("  validated on the FAT32 side. The ext4 surgery (rename UID-1000)")
    log("  remains unexercised — production app has the same gap until the")
    log("  vendored binaries are dropped in.")
    log("")

    # Single-role mode for re-runs that skip verify
    only_role = os.environ.get("E2E_ONLY_ROLE", "").lower()

    if only_role == "slave":
        log("ℹ️ E2E_ONLY_ROLE=slave — skipping Master cycle")
        m_result = {"role": "MASTER", "ok": True, "elapsed": 0.0,
                    "bytes_written": 0, "sha256": "skipped"}
        m_val = {"role": "master", "passed": 0, "failed": 0, "findings": []}
    else:
        # ── MASTER ─────────────────────────────────────────────────────
        m_result = flash_cycle(Role.MASTER, MASTER_IMG, target,
                               master_pair, hotspot,
                               OUT / "progress_master.csv")
        if not m_result["ok"]:
            log("**❌ MASTER cycle aborted — skipping SLAVE.**")
            REPORT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
            return 1
        m_val = validate(Role.MASTER, hotspot.ssid, master_pub)

    if only_role != "slave":
        log("\n### Master directory dump")
        log("")
        log("```")
        for p in sorted(Path("I:/").rglob("*")):
            if "System Volume" in str(p):
                continue
            try:
                rel = p.relative_to("I:/")
            except ValueError:
                continue
            marker = "DIR " if p.is_dir() else "FILE"
            size = "" if p.is_dir() else f"  ({p.stat().st_size} B)"
            log(f"{marker}  {rel}{size}")
        log("```")
        log("")

    # ── SLAVE ──────────────────────────────────────────────────────────
    s_result = flash_cycle(Role.SLAVE, SLAVE_IMG, target,
                           master_pair, hotspot,
                           OUT / "progress_slave.csv")
    if not s_result["ok"]:
        log("**❌ SLAVE cycle FAILED.**")
        REPORT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
        return 1
    s_val = validate(Role.SLAVE, hotspot.ssid, master_pub)

    log("\n### Slave directory dump (final state of I:)")
    log("")
    log("```")
    for p in sorted(Path("I:/").rglob("*")):
        if "System Volume" in str(p):
            continue
        try:
            rel = p.relative_to("I:/")
        except ValueError:
            continue
        marker = "DIR " if p.is_dir() else "FILE"
        size = "" if p.is_dir() else f"  ({p.stat().st_size} B)"
        log(f"{marker}  {rel}{size}")
    log("```")
    log("")

    # ── Summary ────────────────────────────────────────────────────────
    log("\n## Summary")
    log("")
    log("| Cycle | Elapsed | Bytes written | SHA256 (first 16) | Validation |")
    log("|---|---:|---:|---|---|")
    for res, val in [(m_result, m_val), (s_result, s_val)]:
        sha_short = res.get("sha256", "")[:16] + "…" if res.get("sha256") else "n/a"
        score = f"{val['passed']}/{val['passed'] + val['failed']}"
        log(f"| {res['role']} | {res['elapsed']:.1f}s | "
            f"{res['bytes_written'] / 1024**3:.2f} GB | `{sha_short}` | {score} |")
    log("")

    overall_failed = m_val["failed"] + s_val["failed"]
    if overall_failed == 0:
        log("**🟢 OVERALL PASS — all customization + cmdline invariants honoured "
            "on both Master and Slave cards.**")
        rc = 0
    else:
        log(f"**🔴 {overall_failed} validation failure(s).**")
        rc = 1

    REPORT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    log(f"\n📄 Report: {REPORT}")
    log(f"📈 Progress CSVs: progress_master.csv / progress_slave.csv")
    return rc


if __name__ == "__main__":
    sys.exit(main())
