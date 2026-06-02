# 🛠️ AstromechOS Imager

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3127/)
[![PySide6 6.7](https://img.shields.io/badge/PySide6-6.7-41CD52.svg?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Platform: Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg?logo=windows&logoColor=white)](#-distribution--releases)
[![Tests: 504 passing](https://img.shields.io/badge/tests-504%20passing-5ec07a.svg)](#-for-developers)
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
- ✅ **Trust, then write** — SHA‑256 the source *before* flashing, read‑back‑verify the card *after*. Elevated, **pop‑up‑free** raw writes; a cancelled flash leaves a clean, usable card — never a *"Format this disk?"* nag.
- 🎚️ **A UI that doesn't feel like a script** — a frameless, dual‑theme Qt Quick wizard with live drive detection and per‑role progress.

---

## 📸 The wizard

A **frameless, dual‑themed** (dark / light) Qt Quick flow with an R2‑style cobalt accent and a one‑click sun/moon theme toggle — no restart. Screenshots show the **Light** theme (the default on launch).

### Splash

An animated boot splash warms up the engine, then opens into the wizard.

![Splash](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/splash_light.png?v=18)

### Step 1 — Landing

The **Sequential Deployment Assistant**: configure once, then flash the Master and Slave one card at a time — both stamped with the **same `Astromech‑XXXX` rendezvous SSID** (minted at launch) so the two halves find each other on first boot.

![Step 1 — Landing](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step1_landing_light.png?v=18)

### Step 2 — Target Drives

Removable drives are detected live (your system disk is hidden, for safety). One click locks a physical card to its role — **MASTER** or **SLAVE**.

![Step 2 — Target Drives](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step2_target_drives_light.png?v=18)

### Step 3 — Security Validation

Each image earns a badge: **green** = role‑marker verified, **amber** = legacy image trusted by filename, **red** = wrong image → `NEXT` disabled. The flash simply cannot proceed with the wrong card.

![Step 3 — Security Validation](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step3_security_validation_light.png?v=18)

### Step 4 — Customize

Set the robot's **password**, the **private hotspot** that links the two halves, and optional **home Wi‑Fi**. The login name is the fixed `astromech` account (shown read‑only) and the rendezvous SSID is auto‑generated — leave the rest blank for safe defaults, or make them your own.

![Step 4 — Customize](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step4_customize_light.png?v=18)

### Step 5 — Confirm & Flash

A clear summary, an optional SHA‑256 integrity check (on by default), and a destructive `⚡ WRITE` that **never fires on the first click** —

![Step 5 — Confirm & Flash](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step5_confirm_flash_light.png?v=18)

— it raises a bordered **"ERASE TARGET DRIVE(S)?"** modal so you confirm the drive letters before anything irreversible happens.

![Step 5 — WRITE confirmation](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step5_write_confirm_light.png?v=18)

### Step 6 — Complete

Flashed, verified, personalized — with a clear next‑step recap and a `FLASH ANOTHER` shortcut for the second card.

![Step 6 — Complete](https://raw.githubusercontent.com/RickDnamps/AstromechOS_Screenshots/main/Screenshots_Imager/step6_complete_light.png?v=18)

---

## 🔧 Under the hood

Four engineering pillars do the heavy lifting:

- 🤝 **The Handshake** — one `ed25519` keypair, baked into both cards, validated before the card is finalized. The droid comes up married; you reach the body *through* the dome as an SSH bastion.
- 🛡️ **Hard‑blocked validation** — images are virtually mounted in memory and checked against a strict role marker; a mismatch disables `NEXT` with a plain‑English recovery hint.
- ☁️ **cloud‑init provisioning** — the official Raspberry Pi OS Trixie mechanism (`user-data` + `meta-data` + a per‑flash instance‑id) sets the password and resizes the rootfs without ever touching the base image.
- ✅ **Bulletproof Windows writes** — elevated, dismount‑then‑write, userspace FAT customize (no mount → no pop‑ups), deferred partition table, post‑write read‑back verify, and auto‑recovery to a clean exFAT card on cancel/failure — all in pure Python.

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

**504 passing tests** cover the image validator, wizard state, the flash view‑model, the cloud‑init generator, FAT32 boot‑partition I/O, ed25519 keypair generation, first‑boot bundle self‑validation, and end‑to‑end personalization on simulated drives.

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
