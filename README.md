# 🛠️ AstromechOS Imager

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3127/)
[![PySide6 6.7](https://img.shields.io/badge/PySide6-6.7-41CD52.svg?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Platform: Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg?logo=windows&logoColor=white)](#-distribution--releases)
[![Tests: 563 passing](https://img.shields.io/badge/tests-563%20passing-5ec07a.svg)](#)
[![Bundle: 132 MB](https://img.shields.io/badge/bundle-132%20MB-5e9bd6.svg)](#-distribution--releases)
[![Installer: 36 MB](https://img.shields.io/badge/installer-36%20MB-5e9bd6.svg)](#-distribution--releases)

> 🤖 **Companion project** of [AstromechOS](https://github.com/RickDnamps/AstromechOS) — the OS that runs the R2-D2 droid.

The **AstromechOS Imager** is the dedicated, opinionated flashing utility used to deploy AstromechOS onto a fresh pair of Raspberry Pi 4B (Master + Slave). It writes the right image to the right card, wires the **master ↔ slave SSH handshake** automatically, and **hard-blocks** any attempt to flash an unverified or mismatched image — so the droid you turn on at the end is genuinely the droid you intended to build.

---

## 📸 Interface & Walkthrough

The wizard is a **frameless, dark/light dual-themed** flow with hybrid typography (Orbitron for titles / buttons / labels, Segoe UI for body copy so longer text stays readable) and an R2-style cobalt-blue accent that matches the AstromechOS piloting UI. A sun/moon toggle in the header switches themes live without any restart — the screenshots below show the **Light** variant (now the default theme on launch).

### Step 0 — Splash

An old-school standalone splash: the window is sized to the splash artwork's aspect ratio so the **image fills it edge-to-edge with no chrome and no borders** (the app header/footer are hidden, and the PNG's baked-in black bars are cropped at render). A faux **module-loader progress bar** ("Loading drive enumerator", "Mounting image codecs", "Arming flash engine"…) animates across ~4 s in the artwork's lower band, then the window grows into the wizard.

![Step 0 — Splash](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/splash_light.png?v=18)

### Step 1 — Landing

The entry screen of the **Sequential Deployment Assistant**: flash one card at a time, configure once, then deploy Master and Slave with a single shared hotspot SSID. That `Astromech-XXXX` bootstrap SSID is minted **once at launch** (shown read-only in Step 2 and baked into both cards so the wlan0 rendezvous works). `START DEPLOYMENT →` advances to the configuration step.

![Step 1 — Landing](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step1_landing_light.png?v=18)

### Step 2 — Target Drives

Removable drives are enumerated live (system disk is hidden for safety). Each row carries `MASTER` and `SLAVE` assignment buttons that lock the chosen physical device to the chosen role.

![Step 2 — Target Drives](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step2_target_drives_light.png?v=18)

### Step 3 — Security Validation

Once images are selected, the wizard runs the FAT32 role-marker validation (Strategy D) and the filename pattern check in the background. Each image row gets a colored badge: green = certified, amber = legacy without marker but plausible by filename, red = hard mismatch → `NEXT` disabled.

![Step 3 — Security Validation](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step3_security_validation_light.png?v=18)

### Step 4 — Customize

Three groups: the **Linux account**, the **private robot hotspot** (wlan0 link between Master and Slave), and the optional **home Wi-Fi** (wlan1, also configurable later from the robot's web UI). The **username is a fixed system constant** — it renders **read-only** with a 🔒 lock glyph (`astromech`, the account AstromechOS is pre-configured for), so only the **password** is editable; cloud-init applies that password to the existing UID-1000 user on first boot. The bootstrap **hotspot SSID** is likewise shown **read-only** (auto-generated per deployment) directly above its password field, mirroring the locked username. Blank password / hotspot fields fall back to the safe default `astropass`. A prominent security warning reminds the operator there is no recovery mechanism if a custom password is lost.

![Step 4 — Customize](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step4_customize_light.png?v=18)

### Step 5 — Confirm & Flash

Final summary with optional SHA-256 integrity toggle. The destructive `⚡ WRITE` button only goes live after the confirmation dialog and (if enabled) a clean checksum verification. The flashing phase shows live progress per role.

![Step 5 — Confirm & Flash](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step5_confirm_flash_light.png?v=18)

Clicking `⚡ WRITE` does **not** flash immediately — it raises a modal **"ERASE TARGET DRIVE(S)?"** warning with a red 2 px destructive border. The operator must confirm the drive letters match the intended cards and click `⚡ ERASE & WRITE`; `CANCEL` backs out. This is the last guard before the irreversible write.

![Step 5 — WRITE confirmation](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step5_write_confirm_light.png?v=18)

### Step 6 — Complete

Once both cards have been flashed, verified and personalized, the wizard surfaces the next-step recap and a `FLASH ANOTHER` shortcut.

![Step 6 — Complete](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step6_complete_light.png?v=18)

> 🗂️ **For maintainers** — production screenshots are captured locally to `J:\R2-D2_Build\AstromechOS_Screenshots\Screenshots_Imager\` and mirrored to the [`AstromechOS_Screenshots`](https://github.com/RickDnamps/AstromechOS_Screenshots) sibling repository so that this README always renders the latest UI from GitHub raw-content URLs.

---

## 🚀 Project Overview & Architecture

A purpose-built Windows desktop wizard (Python 3.12 + **PySide6 / QML**, distributed as a single signed installer) that drives the entire AstromechOS provisioning pipeline.

### Deployment model

| Mode | What it does |
|---|---|
| **Flash both** *(recommended)* | Writes the Master SD and the Slave SD in **one** session, on two USB SD readers in parallel. Generates a fresh `ed25519` keypair, drops the private half into the Master and the public half into the Slave's `authorized_keys` — the two droid halves come up married. |
| **Master only** | Reuses the persisted keypair from a previous run (or generates a new one on first use), re-flashes just the dome Pi 4B (4 GB). The existing Slave keeps trusting the same Master public key. |
| **Slave only** | Same idea, body Pi 4B (2 GB). Useful when only the body is being rebuilt. |

### First-boot provisioning — cloud-init NoCloud (no system surgery)

The Imager provisions the OS exactly the way the official Raspberry Pi Imager does on Raspberry Pi OS **Trixie** — 100% on the FAT boot partition, leaving the Golden Image untouched:

- **Account + password** — a `#cloud-config` `user-data` (plus a `meta-data` carrying a **unique per-flash `instance-id`**, `rpi-imager-<epoch-ms>`, also pinned on the kernel cmdline via `ds=nocloud;i=…`) is dropped on the boot partition. cloud-init **reconfigures the existing UID-1000 user in place** — `users: []` creates nothing, and `chpasswd` (`type: hash`) sets the SHA-512 password on the fixed `astromech` account. The fresh instance-id forces cloud-init to re-apply on every flash; we never edit `/etc/passwd` or `/etc/shadow` and never rename.
- **Rootfs auto-resize** — the bare `resize` cmdline token triggers Trixie's native initramfs hook (partition grow) and cloud-init's `cc_resizefs` (filesystem grow). No `init=` hack (a wrong PID-1 path bricks boot), no `firstrun.sh`, no offline ext4 surgery — all abandoned.
- **Robot-specific bits stay with the live firstboot** — hostname, dual-WLAN Wi-Fi, the Master↔Slave SSH keypair, the hotspot rendezvous and the role marker are written for `firstboot_setup.sh` (see *The Handshake* below), deliberately **not** in `user-data`, so the two mechanisms never fight.

> The Golden Image's UID-1000 user must be named `astromech` for the password to apply (cloud-init's `chpasswd` targets by name); the base images are standardized on that account.

### Stack at a glance

```
┌───────────────────────────────────────────────────────┐
│ QML (Qt Quick 2 / Controls 2)  ── frameless, dual    │
│  Landing → Config → Images → Role → Ops → Cycle →    │
│           Complete         (Dark + Light themes)     │
├───────────────────────────────────────────────────────┤
│ PySide6 ViewModels (Python)                          │
│  WizardState · FlashViewModel · ThemeManager         │
├───────────────────────────────────────────────────────┤
│ Core engine                                           │
│  imagesource · diskwriter · bootpartition (pyfatfs)  │
│  cloud_init_generator · keygen · image_validator     │
├───────────────────────────────────────────────────────┤
│ Platform IO (Windows-only)                           │
│  WindowsPlatformIO · raw disk handles · WMI drives   │
└───────────────────────────────────────────────────────┘
```

Build chain: **PyInstaller** (`onedir`, custom Qt binary filter — 343 MB → 132 MB) → **Inno Setup** (LZMA2/max, 132 MB → 36 MB installer).

---

## 🔐 Infrastructure & Network Automation (The Handshake)

AstromechOS is a **two-Pi distributed system**. The dome and the body talk to each other constantly over an internal Ethernet/USB link, and that conversation has to *just work* from the very first boot — no manual `ssh-copy-id`, no password prompts, no chicken-and-egg.

The Imager guarantees that by writing a complete, pre-signed network baseline onto the two SD cards.

### Zero-touch master ↔ slave SSH

On every `flash both` session the Imager:

1. **Generates** (or reuses, if persisted in `%APPDATA%\AstromechOS Imager\last_pair\`) a fresh `ed25519` keypair under the comment `astromech-master@imager`.
2. **Writes** the private half to `/astromech_secrets/id_ed25519` on the Master's boot partition. At first boot, AstromechOS's `firstboot_setup.sh` copies it into `/home/<pi-user>/.ssh/id_ed25519` (mode 0600, owned by the install user).
3. **Writes** the matching public half to `/astromech_secrets/authorized_keys` on the **Slave**'s boot partition. Same firstboot script appends it to `~/.ssh/authorized_keys` with `awk '!seen[$0]++'` deduplication.
4. **Self-validates** the bundle before writing the `ASTROMECHOS_FIRSTBOOT_READY` trigger marker — the SD is refused if the Slave's `authorized_keys` does not contain the Master's public key (see `customization.py:_self_validate`).

### Cascade access via ProxyJump

Once both Pis are powered up, the operator's PC reaches the Slave through the Master as a SSH bastion (no need to expose the Slave on any network):

```
~/.ssh/config (on the operator's workstation)

Host astromech-master
    HostName astromech-master.local
    User pi

Host astromech-slave
    HostName astromech-slave.local
    User pi
    ProxyJump astromech-master
```

Result: `ssh astromech-slave` from the workstation transparently hops through the Master, using the Master's bundled key to authenticate to the Slave — zero passwords, zero key shuffling, zero `ssh-copy-id`. The droid's internal network stays a black box.

PC ↔ Master access is intentionally left to the operator (initial password login, then their own `ssh-copy-id` if desired): the Imager never asks the user for an SSH key, the wizard has no key-paste step.

---

## 🛡️ Hard-Blocked Image Validation (Safety Guards)

Flashing the wrong image to the wrong Pi is the single most dangerous failure mode of any imager — it can brick the droid or create a silent master/slave conflict that only surfaces minutes into the first boot.

The Imager defends against this with **two complementary layers**.

### Layer 1 — Structural validation (Strategy D, the hard block)

Every selected image is **virtually mounted in memory** before the wizard accepts it:

1. The first **128 MB** of the image are streamed through `lzma` / `gzip` / `zipfile` (whichever format the operator picked) into a temporary `BytesIO`-backed file on disk — never the full multi-GB image, just enough to contain the FAT32 boot partition's reserved sectors, root directory, and small marker files.
2. The MBR is parsed (`core/bootpartition.find_first_fat32_partition`) to locate the FAT32 boot partition offset.
3. **`pyfatfs`** mounts that region read-only and reads `/astromech_role.json` — the same file path you'd see at `/boot/firmware/astromech_role.json` on a running Pi.
4. The marker is validated against a strict JSON schema:

   ```json
   {
     "role":    "master" | "slave",
     "project": "AstromechOS",
     "version": "2.0"
   }
   ```

5. Any divergence raises a typed exception (`MissingRoleMarkerError`, `MalformedRoleMarkerError`, `WrongProjectMarkerError`, `RoleMismatchError`) that bubbles up to the UI as a **red badge** under the image path and **disables** the `NEXT` button. The wizard refuses to flash, full stop.

Each exception carries a `recovery_hint` written in plain English — for example, on a role mismatch:

> **❌ FLASH BLOCKED: Wrong image for this slot.**
>
> You are about to flash this image into the **MASTER** slot, but the image itself is tagged with role **SLAVE** (per `/astromech_role.json` on its boot partition).
>
> Flashing an image into the wrong Pi can brick the droid or create a silent master/slave conflict that only surfaces on the next boot.
>
> **How to fix:**
>  - either pick an image whose role is `master`,
>  - or change the target slot to `slave`.

### Layer 2 — Filename pattern check (the early indicator)

Before the (slower) FAT32 mount completes, the Imager runs a synchronous regex on the basename and shows a **provisional badge** in the UI:

- `AstromechOS-master-2026-05-29.img.xz` → MASTER family (also: `dome`, `head`)
- `AstromechOS-slave-2026-05-29.img.xz` → SLAVE family (also: `body`, `base`)
- `master_slave_combo.img` → ambiguous → no hint
- `raspios-bookworm.img.xz` → no hint

This costs ~0 ms and gives instant feedback while the daemon thread does the heavyweight FAT32 read in the background. When both signals agree, the badge turns green (`✓ ASTROMECHOS MASTER VERIFIED`). When they disagree, the structural layer wins and the flash is blocked.

> 🟡 **Backwards-compatible escape hatch.** If the marker is **absent** (legacy backups extracted before AstromechOS shipped role markers), and the filename clearly indicates the right role, the badge goes amber (`⚠ NO MARKER FOUND — relying on filename hint`) and lets the operator proceed at their own risk. Filename mismatch on a marker-less image still hard-blocks.

---

## 🎛️ Integrity Verification (SHA-256)

Optional pre-flash checksum verification, toggleable from the **Confirm & Flash** step. **Default: ON.**

### What happens when the toggle is on

When the operator confirms WRITE:

1. The `FlashViewModel` enters the `verifying` state.
2. A dedicated `_HashWorker` runs in a fresh `QThread` and streams the COMPRESSED image file (as downloaded, with no decompression — matching the standard convention of Pi / Ubuntu / Debian releases) through `hashlib` in 1 MB chunks.
3. Progress is emitted to QML and rendered as a cyan progress bar per role — the UI stays fully responsive throughout.

### Sidecar discovery

The Imager auto-discovers and parses checksum files sitting next to the image:

| Candidate | Algorithm |
|---|---|
| `image.sha256` / `image.SHA256` / `image.sha256sum` | SHA-256 |
| `image.md5` / `image.MD5` / `image.md5sum` | MD5 |

Both **bare hex** content and **coreutils** `<hex>  <filename>` format are accepted.

### Verdict

- **Match** → integrity confirmed, the writer is invoked immediately for the destructive phase.
- **Mismatch** → state machine jumps straight to `error`, the writer is **never invoked**. The SD card is not touched.
- **No sidecar found** → the digest is shown on screen with the badge `NO SIDECAR — VERIFY VISUALLY` so the operator can cross-check against the release page before proceeding.

---

## ✅ Windows flash path — elevated, pop-up-free, with post-write SHA-256 readback ON

### Runs as Administrator (required)

Writing raw sectors to a physical drive is a privileged operation on
Windows. The app ships with `requestedExecutionLevel = requireAdministrator`
(set via PyInstaller `uac_admin=True` in `astromechos_imager.spec`), so
**Windows shows the UAC prompt at launch and the process runs elevated** —
just accept it. Without elevation, `CreateFileW(\\.\PHYSICALDRIVEn, …)`,
`DeleteVolumeMountPointW` and the `FSCTL_*` calls all return
`ERROR_ACCESS_DENIED` (errno 5) and nothing is written. The Inno Setup
installer also launches the app elevated; a bare `dist\…\AstromechOS
Imager.exe` double-click now self-elevates the same way.

> ⚠️ If you ever see `errno 5 / ACCESS_DENIED` at the flash step, the
> process is not elevated — relaunch and accept the UAC prompt (or
> right-click → *Run as administrator*).

### Two SHA-256 checks, both ON by default

| When | What it hashes | Toggle | Default |
|---|---|---|---|
| **Pre-flash** | The compressed `.img.gz` / `.img.xz` file on disk | `VERIFY IMAGE INTEGRITY` (Step 5) | **ON** |
| **Post-write readback** | The bytes just written to the SD, re-read from the physical-drive handle | `FlashJob.skip_verify` | **ON** |

Earlier builds disabled the readback on Windows and warned about two modal
Explorer pop-ups — **"Format K:?"** and **"K:\\ is not accessible"**. Both
the pop-ups *and* the post-write checksum mismatch are now fixed in pure
Python (no C++ helper, no service). The mechanisms, in flash order:

1. **Dismount + drop the drive letter** (`lock_and_dismount`). Every volume
   on the target physical drive — found by drive letter *and* by volume GUID
   for letterless volumes — is `FSCTL_LOCK_VOLUME`'d, `FSCTL_DISMOUNT_VOLUME`'d,
   then unlocked and closed; the drive letter is removed from Mount Manager
   with `DeleteVolumeMountPointW`. This runs **before** the physical drive is
   opened. (We do *not* hold the lock for the flash — that path denied
   in-partition writes on real hardware.)
2. **Wipe the in-memory partition layout** (`IOCTL_DISK_DELETE_DRIVE_LAYOUT`
   + `IOCTL_DISK_UPDATE_PROPERTIES` in `open_raw_device`). With no recognised
   partition, the Partition Manager stops policing "in-partition" writes, so
   the FAT32-offset write that otherwise returns `ERROR_ACCESS_DENIED`
   succeeds. The real MBR is restored at the very end (step 4).
3. **Userspace FAT customize, no mount** (`core/raw_fat_partition.py` driving
   `pyfatfs` over a raw-device sector window). The firstboot bundle is
   written without ever asking Windows to mount the FAT32 — no drive letter,
   no Explorer, exactly rpi-imager's `DeviceWrapper` model.
4. **Deferred MBR write** — `DiskWriter` holds back the first 1 MB and the
   orchestrator writes it **last**, after verify and customize. While the MBR
   is absent Windows can't discover a partition to auto-mount, so no pop-up
   fires during the write/verify/customize window. `SHChangeNotify` tells
   Explorer the drive is gone for good measure.

The post-write readback runs on the same `NO_BUFFERING | WRITE_THROUGH`
handle, after `FlushFileBuffers` + SCSI `SYNCHRONIZE_CACHE`, so it reads
on-flash truth rather than USB-bridge cache. The earlier deterministic
readback mismatch was a producer/consumer chunk-drop race in `DiskWriter`,
fixed with a blocking end-of-stream sentinel (never drops a queued chunk).

### What the operator actually sees

- Accept UAC → SHA-256 check → flash → verify readback → personalize →
  **DONE**. No Explorer pop-up at any point, and the post-write readback
  proves the SD card holds exactly the bytes that were written.

### Cancel / failure auto-recovery — card restored to clean exFAT

A flash that is **cancelled** or **fails** mid-write leaves the card RAW:
`open_raw_device` wiped the partition layout up front
(`IOCTL_DISK_DELETE_DRIVE_LAYOUT`) and the real MBR is only written back on
success, so Windows would otherwise see no filesystem and nag *"Format
K:?"* — making the operator think the card is bricked.

To avoid that, `FlashJob.run` tracks whether a valid MBR was written. If the
device was opened but the flash did **not** complete (cancel or error), the
cleanup path best-effort **quick-formats the target to a clean exFAT
volume** (`diskpart`: `clean` → `create partition primary` →
`format fs=exfat quick` → `assign`). The operator gets a normal, recognised
drive back instead of a "broken" one. It is:

- **strictly scoped** to the target `physical_drive_id` (the disk just
  flashed) — never another drive;
- **best-effort** — logs and returns on any error, never raises or hangs, so
  it can't mask the real result or block the cancel;
- **skipped on success** (the freshly-written image is never touched);
- **exFAT**, so it works on any card size (no 32 GB FAT32 limit).

The UI shows a brief `restoring card…` phase while it runs.

---

## 📦 Distribution & Releases

### 🪟 The installer (.exe)

A signed, standalone Windows installer is published on every release in the [Releases section](https://github.com/RickDnamps/AstromechOS_Imager/releases) of this repository:

```
AstromechOS_Imager-Setup-<version>.exe        ~36 MB (LZMA2/max)
```

Built via the project's reproducible chain:

1. **PyInstaller** (`onedir` mode, aggressive `Qt6*.dll` binary filter, OTF font bundling, single-process boot) produces `dist/AstromechOS Imager/` (~132 MB on disk, no extraction lag at launch).
2. **Inno Setup 6** wraps the folder into a single `.exe` with LZMA2/max compression, French + English wizard languages, automatic UAC elevation, Start Menu shortcut and a proper uninstaller.

End users simply double-click the installer, accept UAC, and get a fully integrated Windows application.

### 💾 Official AstromechOS base images

Pre-configured, optimized, and shrunken **AstromechOS base images** for both roles are hosted **directly within the Releases of this project** — same place as the installer, so a fresh build operator downloads two files and never has to clone the AstromechOS repo or build images themselves:

```
AstromechOS-master-<version>.img.xz           ~1.2 GB compressed
AstromechOS-master-<version>.img.xz.sha256    (sidecar, 64-char hex)
AstromechOS-slave-<version>.img.xz            ~1.0 GB compressed
AstromechOS-slave-<version>.img.xz.sha256
```

These images ship with the strict `/astromech_role.json` marker pre-installed — the hard-block validator passes them immediately. They are **shrunken** (rootfs trimmed; the Imager injects the native Trixie `resize` + `ds=nocloud` cmdline tokens at flash time) so downloads stay reasonable while still expanding to fill any ≥ 8 GB SD card on first boot.

---

## 🧪 For Developers

### Requirements

- Windows 10 / 11 (x86_64)
- Python 3.12 (only for development — end users get the bundled `.exe`)
- Administrator rights at runtime (raw disk write + offline ext4 modification)

### Dev install

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
pip install pyinstaller   # for local .exe builds
```

### Run from source

```powershell
.\.venv\Scripts\python.exe -m astromechos_imager.ui.app
```

### Test suite

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Currently **504 passing** tests covering: image validator (43), wizard state (incl. the early-minted bootstrap SSID lifecycle), flash view model, the cloud-init NoCloud generator (user-data / meta-data / cmdline), FAT32 boot partition I/O, ed25519 keypair generation, firstboot bundle self-validation, contract drift vs. the AstromechOS `firstboot_setup.sh` reference, and end-to-end personalization on simulated drives.

### Build the installer locally

See [`BUILD_INSTRUCTIONS.md`](BUILD_INSTRUCTIONS.md) for the two-step PyInstaller → Inno Setup chain (and the gotchas around `console=False`, Qt module trimming, and Windows code signing).

### Capture screenshots for the README

```powershell
.\.venv\Scripts\python.exe scripts\ui_tour.py
```

Outputs 12 PNGs into `screenshots/` (gitignored) — six per theme (dark / light), one per wizard step. These are the source files mirrored into the public `AstromechOS_Screenshots` repo.

---

## 📝 License

[GPL-3.0-or-later](https://www.gnu.org/licenses/gpl-3.0) — same as the [AstromechOS](https://github.com/RickDnamps/AstromechOS) parent project. Free to use, modify, and redistribute; derivatives must stay open under the same terms.

---

<p align="center">
  <em>Part of the <a href="https://github.com/RickDnamps/AstromechOS">AstromechOS</a> droid build ecosystem · 🤖 Made for R2-D2 builders, by an R2-D2 builder.</em>
</p>
