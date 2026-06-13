# Golden Image Build — Authoritative Runbook

> **⚠️ THIS IS THE ONE CORRECT PROCEDURE. Validated end-to-end 2026-06-13.**
> For the cleanup step use **`clean_for_imager.sh` + `dd_state_guard.sh`** (the canonical
> full-clean cycle). **DO NOT** use `dd_master.py` / `dd_slave.py` / `pi_cleanup.sh` for the
> clean — they are the *legacy lighter* pathway and SKIP the NM/SSH wipe, the machine-id
> reset, and the firstboot re-enable → they produce a **broken golden**. (That conflict is
> exactly what caused the 2026-06-12 failure: a robot was left unpaired and a golden would
> have shipped with firstboot disabled.)

## The one correct sequence (per robot)

```
dd_state_guard.sh backup  →  clean_for_imager.sh --yes  →  dd mmcblk0 → SSD  →  dd_state_guard.sh restore
```

run **detached** on the Pi (the clean wipes NetworkManager → drops your SSH tunnel; the
detached script survives and `restore` brings the network back). Then pishrink on the PC.

Full cycle: **prep both robots (Phase A) → DD per robot (Phase B) → pishrink on PC (Phase C).**

---

## 0. Topology & access

| Robot | Address | Reached from the PC via |
|---|---|---|
| **Master** | `192.168.2.104` (wlan1, home Wi-Fi — DHCP, may change) | direct SSH |
| **Slave** | `192.168.4.171` (wlan0, master's hotspot subnet `192.168.4.x`) | **ProxyJump ONLY**: `ssh -J astromech@192.168.2.104 astromech@192.168.4.171` |

- User `astromech`; password is per-deployment (current robots: `astropass`); **`sudo` is passwordless**.
- Non-interactive SSH on Windows (no `sshpass`/`plink`): use OpenSSH's **`SSH_ASKPASS`** helper:
  ```bash
  ASKPASS=$(mktemp); printf '#!/bin/sh\necho astropass\n' > "$ASKPASS"; chmod +x "$ASKPASS"
  SSH_ASKPASS="$ASKPASS" SSH_ASKPASS_REQUIRE=force DISPLAY=:0 \
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null <host> '<cmd>'
  ```
  The same env works for `scp` and for the `-J` jump (one password for both hops).
- **SSD**: USB-3 exFAT, ≥250 GB. Physically moved **slave → master → PC**. On a Pi it is
  `/dev/sda1`, mounted at `/mnt/ssd`. On the PC it mounts as `I:`.

---

## 1. Phase A — prep BOTH robots (BEFORE any DD)

### 1a. Put the *fixed* firstboot script on each Pi

The golden bakes `scripts/firstboot_setup.sh`; it MUST contain the secret-shred fix
(commit `dd0e48f`+ on AstromechOS `main`; marker check: `grep -c "credentials in" …` = 1).

- **Master (git repo):**
  ```bash
  cd /home/astromech/astromechos && git stash && git pull --ff-only origin main
  ```
  (Stash first — the golden ships redundant uncommitted field-fixes that are already in origin.)
- **Slave (NOT a git repo!):** `resync_slave.sh` only syncs `slave/` + `shared/`, **never
  `scripts/`** — so git/rsync will NOT update its firstboot. Push the file directly with
  **`scp`** (do **not** stdin-pipe through ProxyJump — it truncates to an empty file):
  ```bash
  scp -J astromech@192.168.2.104 \
    <PC>/R2-D2_Build/AstromechOS/scripts/firstboot_setup.sh \
    astromech@192.168.4.171:/home/astromech/astromechos/scripts/firstboot_setup.sh
  ```
- Verify on each Pi: `grep -c "credentials in" /home/astromech/astromechos/scripts/firstboot_setup.sh` → **1**.

### 1b. Delete the consumed bootfs secret files

So the golden does not carry the *builder's* secrets (the boot FAT partition is world-readable):

- **Master:** `sudo shred -u /boot/firmware/astromech_init.cfg /boot/firmware/user-data`
- **Slave:** the same **plus** `/boot/firmware/network-config`

These are firstboot-consumed; deleting them does NOT affect a running robot. (The shipped
firstboot fix will shred them automatically on future flashes — this is the manual catch-up
for the current builder cards.)

---

## 2. Phase B — the golden DD, per robot

**Order: SSD on slave → build slave → move SSD to master → build master.** (Either order
works; the `dd` only `rm`s its own role's `*.img`, preserving the other role's image.)

The build runs this **on the Pi** — write it to `/tmp/golden_build.sh`, `bash -n` it,
then launch it detached:

```bash
#!/bin/bash
exec > /tmp/golden_build.log 2>&1
REPO=/home/astromech/astromechos
ROLE=Slave        # Slave | Master
TARGET=/mnt/ssd/AstromechOS_${ROLE}_13-06-2026.img      # <DD-MM-YYYY>
sudo bash "$REPO/scripts/dd_state_guard.sh" backup || { echo "FATAL backup failed"; exit 1; }
sudo bash "$REPO/scripts/clean_for_imager.sh" --yes
sudo mkdir -p /mnt/ssd; sudo umount /mnt/ssd 2>/dev/null; sudo mount -t exfat /dev/sda1 /mnt/ssd
sudo rm -f "/mnt/ssd/AstromechOS_${ROLE}_*.img"
sync; sudo dd if=/dev/mmcblk0 of="$TARGET" bs=4M conv=fdatasync status=progress; sync
sudo umount /mnt/ssd
sudo bash "$REPO/scripts/dd_state_guard.sh" restore
```

**Deploy + launch (robust):**
```bash
scp -J … <local>/golden_build.sh astromech@<pi>:/tmp/golden_build.sh
ssh … <pi> 'bash -n /tmp/golden_build.sh && (setsid nohup bash /tmp/golden_build.sh >/dev/null 2>&1 </dev/null &); echo LAUNCHED'
```

**How to know it is done** — the build log is **not** reliable (`clean_for_imager` empties
`/tmp/`, deleting its own log). Use the state snapshot instead:
`dd_state_guard backup` creates `/dev/shm/astromech_dd_state.tar`; `restore` **removes it at
the very end**. So: poll for that file to **disappear** (after it has appeared). When gone:
verify `stat -c %s <TARGET>` equals `sudo blockdev --getsize64 /dev/mmcblk0`, and the robot is
back (`systemctl is-active astromech-<role>`, `nmcli c show --active`).

### What `clean_for_imager.sh --yes` does — and why each step is mandatory

| Step | Why (anti-recurrence) |
|---|---|
| **Re-enable `astromech-firstboot.service` (+ `rpi-resize`)** | **The Imager CANNOT enable firstboot** — its enable-symlink lives on the **ext4 rootfs**, which the Imager never touches (it only writes the FAT boot partition). A golden built without this ships firstboot **disabled** → fresh flashes never provision (no hotspot, no Flask, no pairing). Autopsy 2026-06-10. |
| Wipe per-deployment NM profiles **+ netplan `90-NM-*.yaml`** + SSH keys | Anti idempotent-skip (2026-06-05): stale builder profiles / a stale master pubkey in the slave's `authorized_keys` make a fresh flash skip its own setup. The firstboot `bootcmd` wipes the `.nmconnection` files but **not** the netplan yaml → the build-time wipe is required. |
| Wipe markers `pair_sealed` / `runcmd_done` / `pair_push_intent` | Else fresh flashes think they are already paired/scrubbed → Master stuck on the bootstrap SSID forever. |
| Reset `machine-id`, create `/var/log/journal`, delete home `angles_backup/` | Unique identity per robot; persistent journald (forensics); no builder servo-calib backup baked into the image. |

`dd_state_guard backup`/`restore` is what keeps the **builder** robot functional afterward:
backup snapshots NM/SSH/markers/machine-id to `/dev/shm` (RAM, can't leak into the DD), restore
re-applies them and re-**disables** firstboot for the builder card.

---

## 3. Phase C — pishrink on the PC

1. Move the SSD to the PC → it mounts as `I:`.
2. Set the date in `scripts/golden_image/pishrink_both.ps1` **line 20** (`$Date = '13-06-2026'`).
3. Run it (from the repo): `& scripts\golden_image\pishrink_both.ps1`
   (per role: copy `I:` → `J:\R2-D2_Build\images\`, `pishrink -a -z` in WSL Debian,
   `gzip -t` integrity check, `Get-FileHash` SHA256 sidecar). pigz removes the intermediate
   `.img` itself.

   > **Always `-a -z`, NEVER `-s`.** pishrink's autoexpand (which `-s` skips) is what grows the
   > ext4 **filesystem** to fill the card on first boot. The Imager's cmdline `resize` token only
   > grows the **partition**, not the FS — an early build wrongly used `-s` and shipped images with
   > a full-size partition but an un-grown ext4 (wasted space). `wsl_pishrink.sh` has been corrected
   > to drop `-s` too; `pishrink_both.ps1` was already correct.
4. **Output (the shippable goldens):**
   ```
   J:\R2-D2_Build\images\AstromechOS_Master_<date>.img.gz   (+ .sha256)
   J:\R2-D2_Build\images\AstromechOS_Slave_<date>.img.gz    (+ .sha256)
   ```
   The pishrunk `.img.gz` IS the canonical format the Imager `.exe` consumes.

> Regenerating a single golden from an existing raw `.img` on the SSD (e.g. a corrupted
> sidecar): copy `I:\AstromechOS_<Role>_<date>.img` → `J:\…\images\`, then in WSL
> `cd /mnt/j/R2-D2_Build/images && /usr/local/bin/pishrink -a -z <name>.img`, `gzip -t`,
> `Get-FileHash`. Read-only on `I:` (Copy only) — never delete from `I:`, it can be your last raw.

---

## ⛔ Mistakes that broke the 2026-06-12 build — DO NOT REPEAT

1. **Wrong cleanup script.** `pi_cleanup.sh` (used by `dd_master.py`/`dd_slave.py`) is the
   *legacy lighter* one: **no** NM/SSH wipe, **no** machine-id reset, **no** firstboot
   re-enable → broken golden. Use **`clean_for_imager.sh`**.
2. **Killing the DD** mid-run → `restore` never runs → robot left in the cleaned state.
3. **Rebooting the builder before `dd_state_guard restore`** → the robot boots in the
   cleaned/unpaired state (markers + NM wiped) → pairing/UART broken. **Never reboot until
   `restore` has run** (i.e. until `/dev/shm/astromech_dd_state.tar` is gone).
4. **Writing the build script via stdin-pipe through ProxyJump** → empty/truncated file →
   nothing runs (the snapshot/log stay empty). Always `scp` the script, then `bash -n` it.
5. **Forgetting the slave firstboot deploy** — the slave is non-git and `resync_slave.sh`
   never touches `scripts/`, so its firstboot stays at the old golden's version unless you scp it.

## Gotchas

- The builder usually **stays reachable** during the build (NetworkManager keeps the active
  connection alive after its profile file is removed, until reload/reboot) — but launch
  **detached** anyway; do not rely on staying connected.
- **JMicron JMS578 USB-SATA bridge** can kill the Pi's xhci controller under sustained DD load
  (`lsusb` goes empty, replug invisible). Remedy: reboot the Pi and relaunch — but if you reboot
  mid-build before `restore`, see mistake #3. Prefer a different bridge.
- Optional pre-pishrink quality gate: `AstromechOS/scripts/verify_golden_image.sh`
  (9-criteria loop-mount ship-state check).

---

*Scripts referenced — PC side (`AstroMechOS_Imager/scripts/golden_image/`):
`pishrink_both.ps1`, `wsl_pishrink.sh`. Pi side (`AstromechOS/scripts/`):
`dd_state_guard.sh`, `clean_for_imager.sh`, `firstboot_setup.sh`, `verify_golden_image.sh`.
`dd_master.py`/`dd_slave.py`/`pi_cleanup.sh` are the legacy pathway — kept for reference, NOT
for the cleanup step.*
