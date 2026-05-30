# 🛠️ AstromechOS Imager

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3127/)
[![PySide6 6.7](https://img.shields.io/badge/PySide6-6.7-41CD52.svg?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Platform: Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg?logo=windows&logoColor=white)](#-distribution--releases)
[![Tests: 437 passing](https://img.shields.io/badge/tests-437%20passing-5ec07a.svg)](#)
[![Bundle: 132 MB](https://img.shields.io/badge/bundle-132%20MB-5e9bd6.svg)](#-distribution--releases)
[![Installer: 36 MB](https://img.shields.io/badge/installer-36%20MB-5e9bd6.svg)](#-distribution--releases)

> 🤖 **Companion project** of [AstromechOS](https://github.com/RickDnamps/AstromechOS) — the OS that runs the R2-D2 droid.

The **AstromechOS Imager** is the dedicated, opinionated flashing utility used to deploy AstromechOS onto a fresh pair of Raspberry Pi 4B (Master + Slave). It writes the right image to the right card, wires the **master ↔ slave SSH handshake** automatically, and **hard-blocks** any attempt to flash an unverified or mismatched image — so the droid you turn on at the end is genuinely the droid you intended to build.

---

## 📸 Interface & Walkthrough

The wizard is a **frameless, dark/light dual-themed** flow with custom Orbitron typography and an R2-style cobalt-blue accent that matches the AstromechOS piloting UI. A sun/moon toggle in the header switches themes live without any restart — the screenshots below show the **Light** variant.

### Splash

The startup splash auto-advances to Step 1 after ~1.5 s. The dark navy chrome stays constant across both themes for visual continuity with the rest of the AstromechOS toolchain.

![Splash](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/splash_light.png)

### Step 1 — Selection

The operator picks **what** to flash: both cards (recommended), only the Master, or only the Slave. R2 line-art glyphs reinforce the choice.

![Step 1 — Selection](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step1_selection_light.png)

### Step 2 — Target Drives

Removable drives are enumerated live (system disk is hidden for safety). Each row carries `MASTER` and `SLAVE` assignment buttons that lock the chosen physical device to the chosen role.

![Step 2 — Target Drives](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step2_target_drives_light.png)

### Step 3 — Security Validation

Once images are selected, the wizard runs the FAT32 role-marker validation (Strategy D) and the filename pattern check in the background. Each image row gets a colored badge: green = certified, amber = legacy without marker but plausible by filename, red = hard mismatch → `NEXT` disabled.

![Step 3 — Security Validation](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step3_security_validation_light.png)

### Step 4 — Confirm & Flash

Final summary with optional SHA-256 integrity toggle. The destructive `⚡ WRITE` button only goes live after the confirmation dialog and (if enabled) a clean checksum verification. The flashing phase shows live progress per role.

![Step 4 — Confirm & Flash](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step4_confirm_flash_light.png)

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

### Stack at a glance

```
┌───────────────────────────────────────────────────────┐
│ QML (Qt Quick 2 / Controls 2)  ── frameless, dual    │
│  Step1Mode → Step2Images → Step3Storage → Step4Flash │
│             → Step5Done    (Dark + Light themes)     │
├───────────────────────────────────────────────────────┤
│ PySide6 ViewModels (Python)                          │
│  WizardState · FlashViewModel · ThemeManager         │
├───────────────────────────────────────────────────────┤
│ Core engine                                           │
│  imagesource · diskwriter · bootpartition (pyfatfs)  │
│  rootfs_personalizer · keygen · image_validator      │
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

These images ship with the strict `/astromech_role.json` marker pre-installed — the hard-block validator passes them immediately. They are **shrunken** (rootfs trimmed and `init_resize.sh` re-injected) so downloads stay reasonable while still expanding to fill any ≥ 8 GB SD card on first boot.

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

Populate `vendor/` with `debugfs.exe`, `e2fsck.exe`, and `msys-2.0.dll` (see `vendor/README.md` for sourcing instructions).

### Run from source

```powershell
.\.venv\Scripts\python.exe -m astromechos_imager.ui.app
```

### Test suite

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Currently **437 passing** tests covering: image validator (43), wizard state, flash view model, FAT32 boot partition I/O, ed25519 keypair generation, firstboot bundle self-validation, contract drift vs. the AstromechOS `firstboot_setup.sh` reference, and end-to-end personalization on simulated drives.

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
