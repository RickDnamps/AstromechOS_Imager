# AstromechOS Imager — Architecture & Internals

The deep-dive companion to the [README](README.md). This document covers the
engineering behind the four pillars: the Master↔Slave handshake, hard-blocked
image validation, cloud-init provisioning, and the elevated pop-up-free Windows
flash path — plus the app stack and build chain.

---

## Deployment model

The wizard is a **Sequential Deployment Assistant**: you configure once, then
flash one card per cycle (Master, then Slave) and `FLASH ANOTHER` loops back for
the next card. Across a session the Imager keeps **one `ed25519` keypair and one
`Astromech-XXXX` rendezvous SSID** so both halves come up married. Re-flashing a
single card later reuses the persisted keypair (from
`%APPDATA%\AstromechOS Imager\last_pair\`), so the existing partner keeps
trusting it.

---

## First-boot provisioning — cloud-init NoCloud (no system surgery)

The Imager provisions the OS exactly the way the official Raspberry Pi Imager
does on Raspberry Pi OS **Trixie** — 100% on the FAT boot partition, leaving the
Golden Image untouched.

- **Account + password.** A `#cloud-config` `user-data` plus a `meta-data`
  carrying a **unique per-flash `instance-id`** (`rpi-imager-<epoch-ms>`, also
  pinned on the kernel cmdline via `ds=nocloud;i=…`) is written to the boot
  partition. cloud-init **reconfigures the existing UID-1000 user in place**:
  `users: []` creates nothing (not even the distro default), and `chpasswd`
  (`type: hash`) sets the SHA-512 password on the fixed `astromech` account. The
  fresh instance-id is what forces cloud-init to re-apply on **every** flash,
  even though the user already exists. We never touch `/etc/passwd` or
  `/etc/shadow`, never rename, and never run an offline ext4 tool.
- **Rootfs auto-resize.** The bare `resize` cmdline token triggers Trixie's
  native initramfs hook (partition grow), and cloud-init's `cc_resizefs` grows
  the filesystem. There is **no `init=` hack** (a wrong PID-1 path bricks first
  boot), no `firstrun.sh`, and no offline ext4 surgery — all abandoned.
- **Robot-specific bits stay with the live first-boot.** Hostname, dual-WLAN
  Wi-Fi, the Master↔Slave keypair, the hotspot rendezvous and the role marker
  are written for `firstboot_setup.sh`, deliberately **not** in `user-data`, so
  the two mechanisms never fight.

> **Golden-image contract:** the base image's UID-1000 user must be named
> `astromech` — cloud-init's `chpasswd` targets by name, and the image's
> cloud-init `default_user` is `pi`, so default-user shortcuts can't reach
> UID-1000. The official base images are standardized on `astromech`.

---

## The Handshake — zero-touch Master ↔ Slave SSH

AstromechOS is a two-Pi distributed system; the dome and body must trust each
other from the very first boot. On a deployment the Imager:

1. **Generates** (or reuses, if persisted) a fresh `ed25519` keypair under the
   comment `astromech-master@imager`.
2. **Writes the private half** to `/astromech_secrets/id_ed25519` on the
   Master's boot partition. At first boot `firstboot_setup.sh` copies it to
   `~/.ssh/id_ed25519` (mode 0600, owned by the account).
3. **Writes the public half** to `/astromech_secrets/authorized_keys` on the
   Slave; the same script appends it to `~/.ssh/authorized_keys`
   (`awk '!seen[$0]++'` dedup).
4. **Self-validates** the bundle before writing the `ASTROMECHOS_FIRSTBOOT_READY`
   trigger — the card is refused if the Slave's `authorized_keys` does not
   contain the Master's public key (`customization.py:_self_validate`).

### Cascade access via ProxyJump

Reach the Slave *through* the Master as an SSH bastion — the droid's internal
network stays a black box:

```sshconfig
# ~/.ssh/config on the operator's workstation
Host astromech-master
    HostName astromech-master.local
    User astromech

Host astromech-slave
    HostName astromech-slave.local
    User astromech
    ProxyJump astromech-master
```

`ssh astromech-slave` transparently hops through the Master using the bundled
key. PC → Master access is intentionally left to the operator (first login by
password, then their own `ssh-copy-id` if desired) — the wizard has no
key-paste step.

---

## Hard-blocked image validation

Flashing the wrong image to the wrong Pi can brick the droid or create a silent
Master/Slave conflict. The Imager defends with two complementary layers.

### Layer 1 — Structural validation (the hard block)

Every selected image is **virtually mounted in memory** before the wizard
accepts it:

1. The first **128 MB** are streamed through `lzma` / `gzip` / `zipfile` into a
   temporary buffer — never the full multi-GB image, just enough to contain the
   FAT32 boot partition's reserved sectors, root directory and marker files.
2. The MBR is parsed (`bootpartition.find_first_fat32_partition`) to locate the
   FAT32 boot partition.
3. `pyfatfs` mounts that region read-only and reads `/astromech_role.json` (the
   same file you'd see at `/boot/firmware/astromech_role.json` on a running Pi).
4. The marker is validated against a strict schema:

   ```json
   { "role": "master" | "slave", "project": "AstromechOS", "version": "2.0" }
   ```

5. Any divergence raises a typed exception (`MissingRoleMarkerError`,
   `MalformedRoleMarkerError`, `WrongProjectMarkerError`, `RoleMismatchError`)
   that bubbles to the UI as a **red badge**, disables `NEXT`, and carries a
   plain-English `recovery_hint`, e.g. on a role mismatch:

   > **❌ FLASH BLOCKED — wrong image for this slot.** This image is tagged
   > `slave`, but you're flashing the **MASTER** card. Pick a `master` image, or
   > switch the slot to `slave`.

### Layer 2 — Filename pattern check (instant indicator)

A synchronous regex on the basename shows a provisional badge while the (slower)
in-memory mount runs in a daemon thread:

- `AstromechOS-master-….img.xz` → MASTER (also `dome`, `head`)
- `AstromechOS-slave-….img.xz` → SLAVE (also `body`, `base`)
- ambiguous / unrelated → no hint

When both signals agree the badge turns green. When they disagree the structural
layer wins and the flash is blocked. A marker-**less** legacy image whose
filename clearly indicates the role gets an amber *"proceed at your own risk"*
pass; a filename that contradicts the marker still hard-blocks.

---

## The Windows flash path — elevated, pop-up-free, verified

Writing raw sectors on Windows is a minefield of permission errors and *"Format
this disk?"* pop-ups. Everything below is pure Python — no C++ helper, no
background service.

### Runs as Administrator (required)

The app ships with `requestedExecutionLevel = requireAdministrator` (PyInstaller
`uac_admin=True`), so Windows shows the UAC prompt at launch and the process
runs elevated. Without elevation, `CreateFileW(\\.\PHYSICALDRIVEn, …)`,
`DeleteVolumeMountPointW` and the `FSCTL_*` calls all return
`ERROR_ACCESS_DENIED` (errno 5) and nothing is written.

> If you ever see `errno 5 / ACCESS_DENIED` at the flash step, the process is
> not elevated — relaunch and accept UAC (or right-click → *Run as
> administrator*).

### Write order

1. **Dismount + drop the drive letter** (`lock_and_dismount`). Every volume on
   the target drive — found by letter *and* by volume GUID for letterless
   volumes — is locked, dismounted, unlocked and closed; the letter is removed
   from Mount Manager. (The lock is **released** before the write — holding it
   denies in-partition writes on real hardware.)
2. **Wipe the in-memory partition layout** (`IOCTL_DISK_DELETE_DRIVE_LAYOUT`).
   With no recognized partition, the Partition Manager stops policing
   "in-partition" writes, so the FAT32-offset write succeeds. The real MBR is
   restored at the very end.
3. **Userspace FAT customize, no mount** (`raw_fat_partition.py` driving
   `pyfatfs` over a raw-device sector window). The cloud-init seed + first-boot
   bundle are written without Windows ever mounting the FAT32 — no drive letter,
   no Explorer, no pop-up.
4. **Deferred MBR write** — `DiskWriter` holds back the first 1 MB and writes it
   **last**, after verify and customize. While the MBR is absent Windows can't
   discover a partition to auto-mount, so nothing pops up during the
   write/verify/customize window.

### Post-write readback

The readback runs on the same `NO_BUFFERING | WRITE_THROUGH` handle, after
`FlushFileBuffers` + SCSI `SYNCHRONIZE_CACHE`, so it reads on-flash truth rather
than USB-bridge cache, and SHA-256-checks it against the source. **On by
default.**

### Cancel / failure auto-recovery

Because the partition layout is wiped up front and the real MBR is only written
back on success, a **cancelled or failed** flash would leave the card RAW (and
Windows would nag *"Format K:?"*). To avoid that, the cleanup path best-effort
quick-formats the target to a clean exFAT volume (`diskpart`: `clean` →
`create partition primary` → `format fs=exfat quick` → `assign`). It is
**strictly scoped** to the drive just flashed, **best-effort** (never raises or
hangs), **skipped on success**, and **exFAT** (works on any card size).

---

## Stack & build chain

```
┌───────────────────────────────────────────────────────┐
│ QML (Qt Quick) — frameless, dual-theme wizard         │
│  Landing → Config → Images → Role → Ops → Cycle → Done │
├───────────────────────────────────────────────────────┤
│ PySide6 ViewModels                                     │
│  WizardState · FlashViewModel · ThemeManager           │
├───────────────────────────────────────────────────────┤
│ Core engine                                            │
│  imagesource · diskwriter · bootpartition (pyfatfs)    │
│  cloud_init_generator · keygen · image_validator       │
├───────────────────────────────────────────────────────┤
│ Platform IO (Windows)                                  │
│  raw disk handles · WMI drive enumeration              │
└───────────────────────────────────────────────────────┘
```

**Build chain:** PyInstaller (`onedir`, aggressive Qt binary trim — ~343 MB →
~132 MB) → Inno Setup 6 (LZMA2/max, French + English wizard, UAC elevation,
Start Menu shortcut, uninstaller — ~132 MB → ~36 MB installer). See
[`BUILD_INSTRUCTIONS.md`](BUILD_INSTRUCTIONS.md).

---

## Integrity verification (SHA-256)

Two independent checks, both **on by default**:

| When | What it hashes |
|---|---|
| **Pre-flash** | the compressed `.img.xz` / `.img.gz` on disk (no decompression, matching Pi/Ubuntu/Debian release convention) |
| **Post-write** | the bytes re-read from the flash after the write |

A dedicated `_HashWorker` streams through `hashlib` in 1 MB chunks on its own
`QThread`, so the UI stays responsive. The Imager auto-discovers checksum
sidecars next to the image (`*.sha256` / `*.md5`, bare-hex or coreutils
`<hex>  <file>` format). **Mismatch → the writer is never invoked, the card is
not touched.** No sidecar → the digest is shown with a *"verify visually"* badge.
