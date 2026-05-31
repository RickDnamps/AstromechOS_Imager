"""Safety audit BEFORE any destructive E2E flash run.

Asserts two preconditions:

1. The Imager's removable-drive filter
   (``astromechos_imager.platform.windows.enumerate_removable_drives``)
   returns EXACTLY ONE drive and that drive is PhysicalDrive7.
   It also dumps the raw WMI list of every Win32_DiskDrive so the
   operator can visually confirm no fixed HDD/SSD is in scope.

2. Each source image in ``J:\\R2-D2_Build\\images\\`` matches its
   ``.sha256`` sidecar. The sidecar is the canonical Bash-style
   "<hex>  <filename>" form that ``sha256sum`` writes.

Exit code is 0 iff both checks pass. Run from project root:

    .venv\\Scripts\\python.exe scripts\\e2e_safety_audit.py

Output:
    screenshots/e2e_audit/SAFETY_AUDIT.md
"""
from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.platform.windows import _wmi_query, enumerate_removable_drives

EXPECTED_PHYS_ID = 7
IMAGES_DIR = Path(r"J:\R2-D2_Build\images")
OUT = Path(__file__).resolve().parents[1] / "screenshots" / "e2e_audit"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / "SAFETY_AUDIT.md"
LINES: list[str] = []


def log(msg: str = "") -> None:
    print(msg)
    LINES.append(msg)


def dump_all_wmi_disks() -> None:
    log("## All Win32_DiskDrive entries (raw WMI dump)")
    log("")
    log("| DeviceID | Size | Model | Interface | MediaType |")
    log("|---|---:|---|---|---|")
    for d in _wmi_query():
        device = (d.DeviceID or "").replace("\\", "\\\\")
        size = int(d.Size or 0)
        size_gb = f"{size / (1024 ** 3):.1f} GB" if size else "0"
        model = (d.Model or "").strip()
        iface = (d.InterfaceType or "").strip()
        media = (d.MediaType or "").strip()
        log(f"| `{device}` | {size_gb} | {model} | {iface} | {media} |")
    log("")


def audit_filter() -> bool:
    log("## Imager's `enumerate_removable_drives()` output")
    log("")
    drives = list(enumerate_removable_drives())
    if not drives:
        log("**❌ NO drives returned** — refuse to flash (would target nothing).")
        return False
    log(f"Filter returned **{len(drives)} drive(s)**:")
    log("")
    log("| phys_id | path | letters | size | model |")
    log("|---:|---|---|---:|---|")
    for d in drives:
        letters = ", ".join(f"{l}:" for l in d.drive_letters) if d.drive_letters else "(none)"
        log(f"| {d.physical_drive_id} | `{d.device_path}` | {letters} | "
            f"{d.size_bytes / (1024 ** 3):.1f} GB | {d.model} |")
    log("")

    if len(drives) != 1:
        log(f"**❌ Expected exactly 1 drive in scope; got {len(drives)}.** STOP — "
            f"the filter is letting through more disks than the operator's "
            f"single inserted SD card.")
        return False

    sole = drives[0]
    if sole.physical_drive_id != EXPECTED_PHYS_ID:
        log(f"**❌ Sole drive is phys_id={sole.physical_drive_id}, expected "
            f"{EXPECTED_PHYS_ID}.** Refuse to proceed — operator must "
            f"replug the intended SD card.")
        return False

    has_i = any(l == "I" for l in sole.drive_letters)
    if not has_i:
        log(f"**⚠️ Sole drive phys_id={sole.physical_drive_id} has letters "
            f"{sole.drive_letters!r} — expected at least 'I' to be present. "
            f"Continuing anyway because the post-flash validator will key "
            f"off whichever letter Windows mounts.**")

    log("**✅ Filter audit PASS** — only the expected removable USB SD card is in scope.")
    log("")
    return True


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def parse_sha256_sidecar(path: Path) -> tuple[str, str] | None:
    """Returns (expected_hex, filename) or None if the file isn't parsable."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    parts = text.split()
    if not parts:
        return None
    return parts[0].lower(), parts[1] if len(parts) > 1 else ""


def audit_images() -> bool:
    log("## Source image SHA256 verification")
    log("")
    if not IMAGES_DIR.exists():
        log(f"**❌ Images directory missing**: `{IMAGES_DIR}`")
        return False
    targets = sorted(IMAGES_DIR.glob("*.img.gz"))
    if not targets:
        log(f"**❌ No .img.gz files in `{IMAGES_DIR}`**")
        return False
    ok = True
    log("| Image | Size | Expected SHA256 (sidecar) | Computed SHA256 | Match |")
    log("|---|---:|---|---|---|")
    for img in targets:
        side = img.with_suffix(img.suffix + ".sha256")
        size_mb = img.stat().st_size / (1024 * 1024)
        if not side.exists():
            log(f"| `{img.name}` | {size_mb:.1f} MB | (sidecar missing) | n/a | ❌ |")
            ok = False
            continue
        expected_pair = parse_sha256_sidecar(side)
        if expected_pair is None:
            log(f"| `{img.name}` | {size_mb:.1f} MB | (sidecar empty) | n/a | ❌ |")
            ok = False
            continue
        expected_hex, _expected_name = expected_pair
        actual_hex = sha256_file(img)
        match = expected_hex == actual_hex
        marker = "✅" if match else "❌"
        log(f"| `{img.name}` | {size_mb:.1f} MB | `{expected_hex[:16]}…` | "
            f"`{actual_hex[:16]}…` | {marker} |")
        if not match:
            ok = False
            log(f"")
            log(f"  Expected full: `{expected_hex}`")
            log(f"  Got      full: `{actual_hex}`")
    log("")
    if ok:
        log("**✅ All source images match their sidecars.**")
    else:
        log("**❌ At least one image failed checksum.** STOP — flashing would "
            "spread corruption to the SD card.")
    return ok


def main() -> int:
    log("# AstromechOS Imager — Safety Audit")
    log("")
    log("Run before any destructive E2E flash. Verifies (1) only the intended")
    log("removable USB SD card is in scope and (2) all source images match")
    log("their checksum sidecars.")
    log("")
    log(f"Expected target: **PhysicalDrive{EXPECTED_PHYS_ID}** (I:)")
    log(f"Image directory: `{IMAGES_DIR}`")
    log("")

    dump_all_wmi_disks()
    ok_filter = audit_filter()
    ok_images = audit_images()

    log("")
    log("## Verdict")
    log("")
    if ok_filter and ok_images:
        log("**🟢 SAFETY AUDIT PASS** — safe to proceed with destructive flash.")
        rc = 0
    else:
        log("**🔴 SAFETY AUDIT FAIL** — fix the items above before any raw write.")
        rc = 1
    REPORT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    log(f"\n📄 Report: {REPORT}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
