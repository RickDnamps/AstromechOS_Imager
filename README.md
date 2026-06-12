# 🛠️ AstromechOS Imager

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3127/)
[![PySide6 6.7](https://img.shields.io/badge/PySide6-6.7-41CD52.svg?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Platform: Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg?logo=windows&logoColor=white)](#-distribution--releases)
[![Tests: 602 passing](https://img.shields.io/badge/tests-602%20passing-5ec07a.svg)](#-for-developers)
[![Installer: 36 MB](https://img.shields.io/badge/installer-36%20MB-5e9bd6.svg)](#-distribution--releases)

> 🤖 Companion to [AstromechOS](https://github.com/RickDnamps/AstromechOS) — the open control platform that makes a 1:1 astromech droid feel *alive*.

## Two Raspberry Pis. One flash session. A droid that wakes up already knowing itself.

[AstromechOS](https://github.com/RickDnamps/AstromechOS) turns a full‑scale astromech into a coordinated, personality‑driven robot — 317 sounds, dozens of behaviors, dome choreography, triple‑watchdog safety. But before any of that magic runs, **two Raspberry Pis** have to be flashed *perfectly* and taught to trust each other:

- 🧠 **Master** — the dome Pi 4B (4 GB): Flask API, web dashboard, choreography player.
- ⚙️ **Slave** — the body Pi 4B (2 GB): drive motors, audio, servos, real‑time I/O.

**AstromechOS Imager is the tool that gets those two brains onto their SD cards — correctly, safely, married.** It writes the right image to the right Pi, bakes in a pre‑signed SSH handshake so the halves trust each other at first boot, provisions the account and network the way the official Raspberry Pi Imager does (native cloud‑init, no hacks), verifies every byte, and **hard‑blocks any mismatched or unverified image before a single sector is written.**

No `dd` gymnastics. No *"wait, which card was the Master?"*. No bricked droid on first boot.

### ✨ Why it's different

- 🛡️ **Wrong‑image hard block** — every image is mounted **in memory** and checked against a cryptographic role marker *before the write button even lights up*. Drop a Slave image into the Master slot and it's blocked cold — with a plain‑English fix, not a cryptic error.
- 🤝 **Zero‑touch droid handshake** — generates an `ed25519` keypair and bakes it into both cards so the dome and body trust each other at first boot. No `ssh-copy-id`, no key shuffling, ever.
- ☁️ **Provisioned like the pros** — user, password, Wi‑Fi and rootfs auto‑resize via **native cloud‑init**, the exact mechanism the official Pi Imager uses on Raspberry Pi OS **Trixie**. The base image is never hacked or surgically edited.
- ✅ **Trust, then write** — runs elevated, SHA‑256‑checks the source *before* flashing and read‑back‑verifies the card *after*, and a cancelled flash leaves a clean, usable card — not a RAW one.
- 🎚️ **A UI that doesn't feel like a script** — a frameless, dual‑theme Qt Quick wizard with live drive detection and per‑role progress.

---

## 📸 The wizard

A **frameless, dual‑themed** (dark / light) Qt Quick flow with an R2‑style cobalt accent and a one‑click sun/moon theme toggle — no restart. Screenshots show the **Light** theme (the default on launch), in the real wizard order.

### Splash

An animated boot splash warms up the engine, then opens into the wizard.

![Splash](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/splash_light.png?v=19)

### Step 1 — Landing

The **Sequential Deployment Assistant**: configure once, then flash the Master and Slave one card at a time — both stamped with the **same `Astromech‑XXXX` rendezvous SSID** (minted at launch) so the two halves find each other on first boot.

![Step 1 — Landing](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step1_landing_light.png?v=19)

### Step 2 — Customize

Set the robot's **password**, the **private hotspot** that links the two halves, and optional **home Wi‑Fi**. The login name is the fixed `astromech` account (shown read‑only) and the rendezvous SSID is auto‑generated — leave the rest blank for safe defaults, or make them your own.

![Step 2 — Customize](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step2_customize_light.png?v=19)

### Step 3 — Select & verify images

Point to your downloaded Master and Slave images. Each one is **virtually mounted in memory** and checked against its role marker — a **green ✓ VERIFIED** badge means it's the genuine article; an amber badge flags a legacy image, and a red one **blocks the flash** for the wrong card.

![Step 3 — Select & verify images](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step3_images_light.png?v=19)

### Step 4 — Insert the card

Removable drives are detected live (your system disk is hidden, for safety). Insert the card for this cycle and lock it to its role — **MASTER** (dome) or **SLAVE** (body).

![Step 4 — Insert the card](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step4_target_drives_light.png?v=19)

### Step 5 — Confirm & flash

A clear summary, an optional SHA‑256 integrity check (on by default), and a destructive `⚡ WRITE` that **never fires on the first click** —

![Step 5 — Confirm & flash](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step5_confirm_flash_light.png?v=19)

— it raises a bordered **"ERASE TARGET DRIVE(S)?"** modal so you confirm the drive letters before anything irreversible happens.

![Step 5 — WRITE confirmation](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step5_write_confirm_light.png?v=19)

### Step 6 — Insert the next card

After the Master is written and verified, the assistant recaps what's flashed (and the shared hotspot SSID), then prompts you to drop in the second card — auto‑assigned to the remaining role.

![Step 6 — Insert the next card](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step6_next_card_light.png?v=19)

### Step 7 — Deployment complete

Both cards flashed, verified and personalized — with a clear next‑step recap (eject, seat each Pi, power on) and a `FLASH ANOTHER` shortcut for the next droid.

![Step 7 — Deployment complete](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step7_complete_light.png?v=19)

---

## 🔧 Under the hood

Four engineering pillars do the heavy lifting:

- 🤝 **The Handshake** — one `ed25519` keypair, baked into both cards, validated before the card is finalized. The droid comes up married; you reach the body *through* the dome as an SSH bastion.
- 🛡️ **Hard‑blocked validation** — images are virtually mounted in memory and checked against a strict role marker; a mismatch disables `NEXT` with a plain‑English recovery hint.
- ☁️ **cloud‑init provisioning** — the official Raspberry Pi OS Trixie mechanism (`user-data` + `meta-data` + a per‑flash instance‑id) sets the password and resizes the rootfs without ever touching the base image.
- ✅ **Hardened Windows writes** — elevated, dismount‑then‑write, userspace FAT customize without mounting the card, deferred partition table, post‑write read‑back verify, and auto‑recovery to a clean exFAT card on cancel/failure — all in pure Python.

📖 **Full technical deep‑dive → [`ARCHITECTURE.md`](ARCHITECTURE.md)** (mechanisms, schemas, the SSH cascade, the Windows flash path, the stack & build chain).

---

## 📦 Distribution & Releases

**The installer.** A signed, standalone Windows installer ships on every [release](https://github.com/RickDnamps/AstromechOS_Imager/releases):

```
AstromechOS_Imager-Setup-<version>.exe        ~36 MB
```

Double‑click, accept UAC, done — Start Menu shortcut, French + English wizard, clean uninstaller.

**Ready‑to‑flash base images.** Pre‑built, role‑marked, shrunken AstromechOS images for both Pis live in the same Releases — download two files, no need to clone or build anything:

```
AstromechOS-master-<version>.img.xz   (+ .sha256)
AstromechOS-slave-<version>.img.xz    (+ .sha256)
```

They pass the hard‑block validator instantly and expand to fill any ≥ 8 GB card on first boot.

---

## 🚦 Good to know

- **It runs as Administrator.** Writing raw sectors to an SD card is a privileged operation — just accept the UAC prompt at launch (the installer wires this up automatically).
- ⚠️ **If Windows pops a *"You need to format the disk"* / *"Format this disk?"* dialog while you're flashing (or right after) — close it, and never click *Format*.** Your card is written and verified correctly; Windows simply can't read a freshly‑written Linux card and assumes it's blank. This is a **Windows limitation** — the official Raspberry Pi Imager behaves exactly the same way. Just dismiss the window and carry on.

---

## 🧪 For Developers

**Requirements:** Windows 10 / 11 (x86_64), Python 3.12 (dev only — end users get the `.exe`), Administrator rights at runtime (raw disk write).

```powershell
# Dev install
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
pip install pyinstaller        # for local .exe builds

# Run from source
.\.venv\Scripts\python.exe -m astromechos_imager.ui.app

# Test suite
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

**602 passing tests** cover the image validator, wizard state, the flash view‑model, the cloud‑init generator, FAT32 boot‑partition I/O, ed25519 keypair generation, first‑boot bundle self‑validation, the anti‑"Format this disk?" defense stack (MBR scrub, sticky‑binding purge, mid‑flash letter watchdog), and end‑to‑end personalization on simulated drives.

- 🏗️ **Architecture & internals:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
- 📦 **Build the installer:** [`BUILD_INSTRUCTIONS.md`](BUILD_INSTRUCTIONS.md) (PyInstaller → Inno Setup)
- 🖼️ **Refresh README screenshots:** `python scripts\ui_tour.py` renders the wizard in both themes (16 PNGs) into the gitignored `screenshots/`, mirrored to the [`AstromechOS_Screenshots`](https://github.com/RickDnamps/AstromechOS_Screenshots) repo.

---

## 🙏 Credits & Inspiration

Huge thanks to the [**Raspberry Pi Imager**](https://github.com/raspberrypi/rpi-imager) team. This project drew heavily on their work — the userspace safe‑write model (dismount, raw‑device customization, deferred partition table), the SHA‑256 verify‑on‑readback pattern, and the cloud‑init / first‑boot provisioning flow were all a major inspiration for the Imager's Windows flash path and provisioning logic. Standing on the shoulders of giants. 🫡

---

## 📝 License

[GPL‑3.0‑or‑later](https://www.gnu.org/licenses/gpl-3.0) — same as the [AstromechOS](https://github.com/RickDnamps/AstromechOS) parent project. Free to use, modify, and redistribute; derivatives stay open under the same terms. Raspberry Pi Imager is © Raspberry Pi Ltd, also under the Apache‑2.0 / GPL terms of its respective components.

---

<p align="center">
  <em>Part of the <a href="https://github.com/RickDnamps/AstromechOS">AstromechOS</a> droid‑build ecosystem · 🤖 Made for astromech builders, by an astromech builder.</em>
</p>
