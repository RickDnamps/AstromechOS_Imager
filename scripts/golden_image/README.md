# `scripts/golden_image/` — Official Golden Image build pipeline

PC-side tooling that produces the `AstromechOS_{Master,Slave}_<date>.img.gz` Golden Images consumed by the AstroMechOS_Imager `.exe` at flash time. All scripts run on the dev PC; they SSH into a live Pi and capture its `mmcblk0` to a Golden Image.

> **History:** Refined during the 2026-06-02 → 2026-06-07 debug marathon (9 architectural bugs fixed across AstromechOS + Imager). The anti-regression invariants documented here are GRAVED in stone — see `AstromechOS/docs/AUDIT_HISTORY.md` Phase 33 + `AstromechOS/docs/FIRSTBOOT.md` §3.

---

## Files

| Script | Runs where | Role |
|---|---|---|
| `pi_cleanup.sh` | On Pi (master OR slave), as root | Pre-DD cleanup: truncate logs, vacuum journal, clear bash history, drop caches, sync. Called by `dd_master.py` + `dd_slave.py` automatically. |
| `dd_master.py` | On PC (Python 3.12+ with paramiko) | SSH master Pi → mount SSD → pi_cleanup → DD `/dev/mmcblk0` → SSD. Auto-detects size. |
| `dd_slave.py` | On PC | PC → master tunnel → slave. Same flow on slave. Master.img preserved on SSD. |
| `pishrink_both.ps1` | On PC (PowerShell + WSL Debian) | Copy `I:` → `J:\images\`, pishrink both, generate SHA256 sidecars. |
| `wsl_pishrink.sh` | In WSL Debian on PC, as root | Lower-level pishrink wrapper (kept for ad-hoc single-image runs; `pishrink_both.ps1` is the canonical entry point). |

---

## Prerequisites

### On the dev PC (Windows)

| Tool | Install | Why |
|---|---|---|
| Python 3.12+ | python.org | `dd_master.py` + `dd_slave.py` runtime |
| `paramiko` | `pip install paramiko` | SSH client used by the dd scripts (sshpass not available on Windows) |
| PowerShell 5+ | preinstalled on Win 10/11 | `pishrink_both.ps1` runtime |
| WSL2 + Debian | `wsl --install -d Debian` | Hosts pishrink (Pi OS-compatible loop-mount env) |
| `pishrink` in WSL | `wsl -d Debian -u root -- bash -c "curl -fsSL https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh -o /usr/local/bin/pishrink && chmod +x /usr/local/bin/pishrink"` | Shrinks the .img |
| `pigz` in WSL | `wsl -d Debian -u root -- apt install -y pigz` | Parallel gzip for `-a` flag |

### On the Pi (master AND slave)

| Tool | Install | Why |
|---|---|---|
| `exfatprogs` | `apt install -y exfatprogs` (Trixie) | Mounts the SSD which is exFAT-formatted |
| `blockdev` | preinstalled (util-linux) | Used to auto-detect `mmcblk0` size |
| `dd` | preinstalled (coreutils) | The actual image copy |
| `pgrep` / `pkill` | preinstalled (procps) | Used by recovery (kill stuck DD) |

### On the SSD (USB-attached, exFAT-formatted)

- **Partition 1** at `/dev/sda1` formatted exFAT (or whichever USB-letter the Pi assigns — auto-detected via `lsblk` in `dd_master.py`)
- Mounted to `/mnt/ssd` (auto-mounted by `dd_master.py`; `dd_slave.py` also mounts before DD)
- 250 GB+ recommended (master 128 GB + slave 64 GB = ~200 GB worst case, plus headroom)

---

## Workflow — Production Golden Image build (~85 min total)

### Step 1 — Prep the source Pis (~5 min, manual)

Both master AND slave should be **fresh-flashed from a current Golden Image** OR a verified legacy. The state captured here becomes the next Golden Image. Wipe per-deployment markers BEFORE DD to prevent operator state leak:

```bash
# On master Pi (via SSH from PC):
ssh astromech@192.168.2.104   # password depends on which generation: legacy=astropass, flashed=astropass123
sudo rm -f /var/lib/astromech/pair_sealed /var/lib/astromech/runcmd_done

# On slave Pi:
ssh -J astromech@192.168.2.104 astromech@192.168.4.171
sudo rm -f /var/lib/astromech/runcmd_done   # slave has no pair_sealed (master-only)
```

**⚠️ Anti-recurrence #7** — Skip this step and the distributed flashed Pis will skip pair-sealing forever (stuck on bootstrap SSID) and inherit your `~/.ssh/id_ed25519`. See `AstromechOS/docs/AUDIT_HISTORY.md` Phase 33.

### Step 2 — Master DD (~25-50 min depending on SD size)

```powershell
# Attach SSD via USB to the master Pi.
# Then on PC:
cd J:\R2-D2_Build\AstroMechOS_Imager\scripts\golden_image
python -u .\dd_master.py
```

The script:
1. SSH master Pi (config at the top of the file — IP + password)
2. Detects the SSD via `lsblk` (looks for the only USB disk)
3. Auto-detects `mmcblk0` size via `blockdev --getsize64 /dev/mmcblk0`
4. Mounts SSD as exFAT to `/mnt/ssd`
5. SCPs + runs `pi_cleanup.sh master`
6. `dd if=/dev/mmcblk0 of=/mnt/ssd/AstromechOS_Master_<date>.img bs=4M conv=fdatasync`
7. Verifies output size matches `mmcblk0`

Polls progress every 60s via separate SSH session — final output reaches the user even if dd's `status=progress` stderr buffer fills up.

### Step 3 — Transfer SSD to Slave Pi (~30s, manual)

Unplug USB SSD from master Pi → plug into slave Pi.

### Step 4 — Slave DD (~13-25 min)

```powershell
python -u .\dd_slave.py
```

Same flow as master, but via PC → master tunnel → slave. `Master.img` is preserved on the SSD; only `Slave_*.img` is rm'd by `pi_cleanup.sh`.

### Step 5 — Transfer SSD to PC (~30s, manual)

Unplug USB SSD from slave Pi → plug into PC. Should mount as `I:`.

### Step 6 — Pishrink both (~15-20 min)

```powershell
.\pishrink_both.ps1
```

For each role (Master then Slave):
1. Auto-detects size via `(Get-Item I:\<img>).Length` (anti-regression: no hardcoded EXPECTED)
2. Copies `I:\<img>` → `J:\R2-D2_Build\images\<img>` (~10 min)
3. WSL Debian: `pishrink -a -z <img>` → `<img>.gz` (~5 min, parallel pigz)
4. `gzip -t` integrity check
5. Removes intermediate `.img` (saves 60+ GB transient)
6. `Get-FileHash -Algorithm SHA256` → sidecar file

### Step 7 — Final state

```
J:\R2-D2_Build\images\
├── AstromechOS_Master_<date>.img.gz       ~1.2 GB
├── AstromechOS_Master_<date>.img.gz.sha256
├── AstromechOS_Slave_<date>.img.gz        ~1.1 GB
└── AstromechOS_Slave_<date>.img.gz.sha256
```

These are the inputs to the AstroMechOS_Imager `.exe`. Operator points the Imager at them and flashes.

---

## Anti-regression invariants (NEVER weaken these)

These were learned the hard way during the 5-day marathon. Each invariant has corresponding test coverage and is referenced in `AstromechOS/CLAUDE.md` §"🏗️ Golden Image build invariants".

| # | Invariant | Enforcement | Reference |
|---|---|---|---|
| 1 | Per-deployment markers wiped pre-DD | Manual (Step 1) — TODO: add to `pi_cleanup.sh` | See marathon root cause #7 |
| 2 | `EXPECTED_SIZE` auto-detected, NEVER hardcoded | `EXPECTED_SIZE = None` sentinel at module top | dd_master.py:20, dd_slave.py:23, pishrink_both.ps1:22 |
| 3 | Persistent journal directory created | TODO: add to `pi_cleanup.sh` for next Golden Image build | See root cause #6 |
| 4 | SSD explicitly mounted by scripts (no fstab assumption) | dd_master.py A2 block, dd_slave.py B block | Flashed Pi has no fstab auto-mount |
| 5 | DD uses `stream=False` + poll thread | dd_master.py F block, dd_slave.py H block | paramiko readline times out on long dd |
| 6 | gzip integrity check after pishrink | pishrink_both.ps1 (gzip -t per role) | USB-SATA thermal saturation can corrupt silently |
| 7 | Imager bake = single source of truth for per-deployment creds | OUT OF SCOPE here — see `AstroMechOS_Imager/astromechos_imager/core/customization.py` + `AstromechOS/scripts/firstboot_setup.sh` | NEVER hand-set state on legacy with operator-specific values |

---

## Why pishrink uses `-a -z` (NOT `-s`)

- `-a` = parallel gzip via `pigz` (uses all CPU cores)
- `-z` = output `.img.gz` directly (no intermediate decompressed .img on J:)
- NO `-s` because the AstroMechOS_Imager already injects native Trixie resize (`resize_early` initramfs hook + cloud-init `cc_resizefs`) via `astromechos_imager/core/cloud_init_generator.py`. Adding `-s` would create a doublon resize and pollute the rootfs with an unused `/etc/rc.local` (rc-local.service is disabled by default on Trixie).

---

## Why pishrink runs on PC, NOT on Pi

- Slave Pi has 2 GB of RAM. `e2fsck + resize2fs + pigz` parallel easily exceeds 2 GB → OOM thrashing.
- Master Pi has 4 GB but its Flask + drivers stack runs continuously → insufficient headroom.
- WSL2 on PC has access to all host RAM (16+ GB typical) → zero OOM risk.

---

## Why USB 3.0 SSD instead of USB-SD adapter

- USB-SD adapter typical = USB 2.0 = 30 MB/s = **4 hours for a 128 GB SD**.
- External SATA SSD + USB 3.0 SuperSpeed adapter = 40-90 MB/s sustained SD read = **~50 min for the same 128 GB SD** (down to ~25 min for a 64 GB SD).
- SSD stays plugged to the Pi for the entire DD (zero physical movement mid-write), then moves to PC for pishrink.

---

## Troubleshooting

### "DD exits with size mismatch but the image looks right"

You're running an OLD version with hardcoded `EXPECTED_SIZE`. `git pull` + re-run. The current scripts auto-detect via `blockdev --getsize64` — verify by reading `dd_master.py:65-68` for the A1 block.

### "exfat mount fails on the Pi"

```bash
# On Pi:
sudo apt install -y exfatprogs    # Trixie package (was exfat-utils on Bullseye)
```

### "wsl pishrink reports 'no such file'"

The scripts use `wsl -d Debian -u root -- bash -c "cd /mnt/j/... && pishrink ..."`. The `bash -c "cd ... && ..."` wrapper is the proven pattern from the marathon — bare `wsl ... pishrink /mnt/j/...` fails on WSL path translation. Don't simplify the invocation.

### "paramiko AuthenticationException"

Check the `PWD` constant at the top of the script. Legacy Pis use `astropass`. Flashed Pis use whatever the operator entered as `installPassword` in the Imager wizard (default `astropass123` per `AstroMechOS_Imager/astromechos_imager/core/models.py::DEFAULT_INSTALL_PASSWORD`).

### "Pi reachable on 192.168.2.x but no SSD detected"

The SSD wasn't recognized as a USB disk. Verify on Pi: `lsblk -dno NAME,SIZE,TYPE,TRAN`. Look for a row where `TRAN=usb` and `TYPE=disk`. If absent, the USB-SATA bridge may have thermal-saturated (JMicron JMS578) — power-cycle the Pi + unplug+replug SSD.

---

## Related docs

- `AstromechOS/docs/AUDIT_HISTORY.md` — Phase 33 entry covers the 9-bug marathon in full
- `AstromechOS/docs/FIRSTBOOT.md` §3 — Imager↔firstboot contract + 2 anti-recurrence callouts
- `AstromechOS/CLAUDE.md` §"🚨 Recovery procedures" — operator playbook for "the 4 most expensive bugs"
- `AstromechOS/CLAUDE.md` §"🏗️ Golden Image build invariants" — the standing rules
