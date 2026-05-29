# AstromechOS Imager — Manual E2E Checklist

Run before each release. Requires real hardware: two SD cards, two USB readers,
and an AstromechOS-compatible Raspberry Pi 4B pair.

Source: design spec §8.5 — Layer 4: manual E2E (real hardware).

---

## Pre-conditions

- [ ] Windows 10/11 machine, admin rights available
- [ ] Two SD cards (≥ 8 GB) inserted via USB
- [ ] Master image file (`*.img.xz` or `*.img`) available
- [ ] Slave image file (`*.img.xz` or `*.img`) available
- [ ] `vendor/` populated with `debugfs.exe`, `e2fsck.exe`, `msys-2.0.dll`

---

## 1. Drive detection

- [ ] Launch AstromechOS Imager (or `astromechos-imager` CLI)
- [ ] Confirm both SD cards appear in the drive selector
- [ ] Confirm system drives (C:, D:, etc.) are NOT listed
- [ ] Swap a card for a non-SD-card device — confirm it is absent from the list (WMI type filter)

---

## 2. Flash both (Master + Slave) mode

- [ ] Select "Flash both" mode
- [ ] Pick the Master image; verify SHA-256 pre-check completes without error
- [ ] Pick the Slave image; verify SHA-256 pre-check completes without error
- [ ] Select Drive A as Master target; Drive B as Slave target (confirm different drives)
- [ ] Fill customization fields:
  - Hostname Master: `astromech-master`
  - Hostname Slave: `astromech-slave`
  - SSH public key: paste a test key or browse to `~/.ssh/id_ed25519.pub`
  - Linux username: `artoo` (or any valid username)
  - Linux password: any non-empty string (shown once in UI)
  - Hotspot SSID: auto-generated or custom
- [ ] Click **Flash** — confirm progress bars for Master and Slave appear
- [ ] Wait for completion on both cards — confirm "Flash complete" dialog (no errors)
- [ ] Confirm log file created at `%APPDATA%\AstromechOS Imager\logs\flash-*.log`

---

## 3. Boot and first-boot provisioning

### 3.1 Master

- [ ] Insert Master SD card into Pi 4B (Master unit)
- [ ] Power on Master Pi
- [ ] Confirm `/boot/ASTROMECH_FIRSTBOOT_READY` is deleted after ~2 min (first boot ran)
- [ ] Check `/var/log/astromech-firstboot.log` — no `[ERR]` lines
- [ ] Verify hostname is set: `hostname` returns `astromech-master`
- [ ] Verify SSH authorized_keys injected: `cat ~/.ssh/authorized_keys` shows test key
- [ ] Verify hotspot interface comes up: `nmcli con show` shows `astromech-hotspot` profile

### 3.2 Slave

- [ ] Insert Slave SD card into Pi 4B (Slave unit)
- [ ] Power on Slave Pi
- [ ] Confirm first-boot completes (marker deleted)
- [ ] Check `/var/log/astromech-firstboot.log` — no `[ERR]` lines
- [ ] Verify hostname: `hostname` returns `astromech-slave`
- [ ] Verify `astromech-master-hotspot` nmcli profile exists

---

## 4. Master → Slave handshake

- [ ] With both Pis on the same LAN (or via the bootstrap hotspot), verify Master can reach Slave:
  - `ping astromech-slave.local` from Master (or known IP)
- [ ] Verify Master → Slave SSH works (keypair injected at flash time):
  - `ssh -i ~/.ssh/id_ed25519 artoo@astromech-slave.local`
  - Should not prompt for password

---

## 5. Single-role mode (regression)

- [ ] Flash only a Master card (single-role mode) — no Slave selected
- [ ] Confirm only one progress bar appears
- [ ] Confirm card boots and first-boot completes without requiring a Slave

---

## 6. Cancel mid-flash

- [ ] Start a flash; click **Cancel** during the write phase
- [ ] Confirm dialog says "Drive contains partial data — not bootable"
- [ ] Confirm SD card is in `GARBAGE` state (safe to re-flash)

---

## 7. Diagnostic export

- [ ] After a flash (or simulated error), open Help → Export Diagnostic
- [ ] Confirm ZIP is created at user-chosen path
- [ ] Open ZIP: confirm `session.log`, `traceback.txt`, `system_info.json`, `firstboot_config.json` are present
- [ ] Confirm `firstboot_config.json` does NOT contain `hotspot_password` or `cleartext_password`
- [ ] Re-export with "Include PSK" checked — confirm `hotspot_password` IS present

---

## 8. Sign-off

| Tester | Date | Result | Notes |
|---|---|---|---|
| | | PASS / FAIL | |
