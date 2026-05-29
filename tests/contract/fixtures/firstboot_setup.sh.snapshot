#!/usr/bin/env bash
# ============================================================================
# scripts/firstboot_setup.sh — AstromechOS first-boot provisioning.
#
# Runs ONCE at the very first boot of a freshly-imaged SD card. Triggered by
# the systemd oneshot `astromech-firstboot.service` if and only if the marker
# file `/boot/ASTROMECH_FIRSTBOOT_READY` is present. The AstromechOS Imager
# (PC tool) prepares the SD card BEFORE flashing by writing:
#
#   /boot/ASTROMECH_FIRSTBOOT_READY            (trigger marker — deleted at end)
#   /boot/astromech_init.cfg                   (cfg-style bootstrap, read by
#                                                lib_config.sh::cfg_get during
#                                                install and by this script
#                                                for misc settings)
#   /boot/astromech_secrets/  (chmod 0700)
#       init_config.json                       ({role,hostname,...})
#       authorized_keys                        (OpenSSH public keys, one per
#                                                line — appended to the
#                                                target user's authorized_keys)
#       id_ed25519 + id_ed25519.pub            (optional — robot's own keypair
#                                                for outbound SSH; only useful
#                                                on the Master for the
#                                                Master→Slave authorized push)
#
# Workflow:
#   1. Bail if the trigger marker is absent (defensive — nothing to do).
#   2. Source lib_config.sh; run capture_user to set TARGET_USER + TARGET_HOME
#      from /boot/astromech_init.cfg [system] user → $SUDO_USER → ...
#   3. Inject SSH public keys from /boot/astromech_secrets/authorized_keys
#      into $TARGET_HOME/.ssh/authorized_keys (atomic; perms 0600;
#      owned by $TARGET_USER). Copy the optional id_ed25519* keypair.
#   4. Parse /boot/astromech_secrets/init_config.json → hostname + role.
#      Set hostname via hostnamectl. Persist [system] role = master|slave
#      to local.cfg via write_local_cfg.
#   5. If a custom github.repo_url is configured (via /boot/astromech_init.cfg
#      or local.cfg [github] repo_url) AND it differs from origin's current
#      URL: DNA-validate via dna_validate. If valid, switch origin +
#      `git reset --hard origin/<branch>`. If invalid, log + KEEP origin
#      pointed at the (presumably official) original.
#   6. Self-destruct: rm the trigger marker, shred + rmdir the secrets
#      directory, sync, reboot.
#
# Idempotency: every step is safe to re-run on its own; we only delete the
# trigger in step 6, so a crashed run can be retried by simply re-booting.
# All output is captured to /var/log/astromech-firstboot.log AND echoed.
#
# Must be invoked as root (it writes /etc/hostname, /var/log, /boot, ...)
# from the systemd service astromech-firstboot.service.
# ============================================================================

set -u   # treat unset vars as error; DO NOT use `set -e` here — we want to
         # keep going even if a sub-step fails, so the operator can SSH in
         # later and finish manually rather than be locked out of a brick.

# ─── Logging ─────────────────────────────────────────────────────────────
LOGFILE="/var/log/astromech-firstboot.log"
mkdir -p /var/log
log() { local m; m="[$(date -Iseconds)] $*"; echo "$m" | tee -a "$LOGFILE" >&2; }
log_ok()  { log "[OK]   $*"; }
log_warn(){ log "[WARN] $*"; }
log_err() { log "[ERR]  $*"; }
log "=========================================="
log "AstromechOS firstboot_setup.sh starting"
log "=========================================="

# ─── 1. Trigger marker check ────────────────────────────────────────────
TRIGGER="/boot/ASTROMECH_FIRSTBOOT_READY"
[ -f "/boot/firmware/ASTROMECH_FIRSTBOOT_READY" ] && TRIGGER="/boot/firmware/ASTROMECH_FIRSTBOOT_READY"
if [ ! -f "$TRIGGER" ]; then
    log "No trigger marker at $TRIGGER — nothing to do."
    exit 0
fi
log_ok "Trigger marker found: $TRIGGER"

# ─── /boot path discovery ───────────────────────────────────────────────
# Pi OS Bookworm + uses /boot/firmware/. Both layouts supported.
BOOT_DIR="/boot"
[ -d "/boot/firmware" ] && BOOT_DIR="/boot/firmware"
SECRETS_DIR="$BOOT_DIR/astromech_secrets"
INIT_CFG="$BOOT_DIR/astromech_init.cfg"
INIT_JSON="$SECRETS_DIR/init_config.json"
AUTH_KEYS_SRC="$SECRETS_DIR/authorized_keys"
log_ok "BOOT_DIR=$BOOT_DIR  SECRETS_DIR=$SECRETS_DIR"

# ─── 2. Identify the install user (TARGET_USER + TARGET_HOME) ───────────
# capture_user looks in /boot/astromech_init.cfg [system] user first, then
# falls through to $SUDO_USER / logname / 'artoo' legacy.
REPO_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib_config.sh
. "$REPO_PATH/scripts/lib_config.sh"

# We're running as root (systemd unit). The "install" user is the one
# whose home will receive the SSH keys + own the repo install. capture_user
# normally errors if it can't auto-detect; for firstboot we accept whatever
# /boot says, else fall back to 'pi' if it exists, else 'artoo'.
if ! capture_user 2>/dev/null; then
    for u in pi astromech artoo; do
        if id "$u" &>/dev/null; then
            TARGET_USER="$u"
            TARGET_HOME=$(getent passwd "$u" | cut -d: -f6 || echo "/home/$u")
            export TARGET_USER TARGET_HOME
            break
        fi
    done
fi
if [ -z "${TARGET_USER:-}" ] || ! id "$TARGET_USER" &>/dev/null; then
    log_err "Cannot resolve a valid target user — aborting (keeping trigger so a retry is possible)."
    exit 2
fi
log_ok "Target user: $TARGET_USER  home: $TARGET_HOME"

# ─── 3. SSH key injection ────────────────────────────────────────────────
# Append every PUBLIC key in $SECRETS_DIR/authorized_keys to the target
# user's ~/.ssh/authorized_keys, atomically and with strict perms. The
# optional id_ed25519 keypair (private + public) is copied into ~/.ssh/
# so the Master can SSH OUT to the Slave from boot one (Imager generates
# the pair once, writes the public half to the Slave's authorized_keys
# via this same mechanism).
SSH_DIR="$TARGET_HOME/.ssh"
mkdir -p "$SSH_DIR"
chmod 0700 "$SSH_DIR"
chown "$TARGET_USER:$TARGET_USER" "$SSH_DIR"

if [ -f "$AUTH_KEYS_SRC" ]; then
    # Atomic append: copy current → tmp → append source → mv back
    TMP_AK="$(mktemp -p "$SSH_DIR" .authkeys.XXXXXX)"
    if [ -f "$SSH_DIR/authorized_keys" ]; then
        cat "$SSH_DIR/authorized_keys" > "$TMP_AK"
    else
        : > "$TMP_AK"
    fi
    # Strip stray CR/empty lines from the Imager-supplied file
    awk 'NF' "$AUTH_KEYS_SRC" | tr -d '\r' >> "$TMP_AK"
    # Dedupe (sort -u would reorder; awk preserves first-seen order)
    awk '!seen[$0]++' "$TMP_AK" > "$TMP_AK.dedup"
    mv "$TMP_AK.dedup" "$SSH_DIR/authorized_keys"
    rm -f "$TMP_AK"
    chmod 0600 "$SSH_DIR/authorized_keys"
    chown "$TARGET_USER:$TARGET_USER" "$SSH_DIR/authorized_keys"
    NB_KEYS=$(awk 'NF' "$SSH_DIR/authorized_keys" | wc -l)
    log_ok "authorized_keys: $NB_KEYS key(s) installed for $TARGET_USER"
else
    log_warn "No $AUTH_KEYS_SRC — skipping SSH key injection (operator must enable SSH manually)"
fi

# Optional outbound keypair (Master → Slave)
for k in id_ed25519 id_ed25519.pub id_rsa id_rsa.pub; do
    SRC="$SECRETS_DIR/$k"
    if [ -f "$SRC" ]; then
        cp -p "$SRC" "$SSH_DIR/$k"
        chown "$TARGET_USER:$TARGET_USER" "$SSH_DIR/$k"
        case "$k" in
            *.pub) chmod 0644 "$SSH_DIR/$k" ;;
            *)     chmod 0600 "$SSH_DIR/$k" ;;
        esac
        log_ok "outbound key installed: ~/.ssh/$k"
    fi
done

# ─── 4. Identity (role + hostname) from init_config.json ────────────────
ROLE=""
HOSTNAME_TARGET=""
if [ -f "$INIT_JSON" ]; then
    log_ok "Reading $INIT_JSON"
    ROLE=$(_python - "$INIT_JSON" 'role' << 'PYEOF' 2>>"$LOGFILE" || true
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        d = json.load(f)
    print(str(d.get(sys.argv[2], '')).strip().lower())
except Exception as e:
    print('', file=sys.stderr); sys.exit(0)
PYEOF
)
    HOSTNAME_TARGET=$(_python - "$INIT_JSON" 'hostname' << 'PYEOF' 2>>"$LOGFILE" || true
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        d = json.load(f)
    print(str(d.get(sys.argv[2], '')).strip())
except Exception as e:
    print('', file=sys.stderr); sys.exit(0)
PYEOF
)
    log_ok "Parsed role='$ROLE'  hostname='$HOSTNAME_TARGET'"
else
    log_warn "No $INIT_JSON — role/hostname not configured (using defaults below)"
fi

# Validate + default role
case "$ROLE" in
    master|slave) ;;
    *)
        # Heuristic: any Pi without internet on wlan0 is most likely the Slave
        # (it joins the Master's hotspot). But this is best-effort only —
        # for true headless install the Imager MUST set role explicitly.
        log_warn "role missing/invalid in init_config.json; defaulting to 'master'"
        ROLE=master ;;
esac

# Apply hostname (compute from role if not explicit)
if [ -z "$HOSTNAME_TARGET" ]; then
    HOSTNAME_TARGET="astromech-$ROLE"
fi
# Strict charset (RFC 1123) — refuse if the Imager wrote garbage
if [[ "$HOSTNAME_TARGET" =~ ^[a-zA-Z0-9](-?[a-zA-Z0-9])*$ ]] && [ ${#HOSTNAME_TARGET} -le 63 ]; then
    if [ "$(hostname)" != "$HOSTNAME_TARGET" ]; then
        hostnamectl set-hostname "$HOSTNAME_TARGET" \
            && log_ok "hostname set: $HOSTNAME_TARGET" \
            || log_err "hostnamectl failed"
        # Update /etc/hosts so 127.0.1.1 resolves to the new name
        sed -i -E "s/^127\.0\.1\.1\s+.*/127.0.1.1\t$HOSTNAME_TARGET/" /etc/hosts || true
    else
        log_ok "hostname already $HOSTNAME_TARGET"
    fi
else
    log_warn "invalid hostname '$HOSTNAME_TARGET' — leaving system hostname unchanged"
fi

# Persist role in local.cfg so runtime code knows who it is
if [ -n "$ROLE" ]; then
    if write_local_cfg system role "$ROLE"; then
        log_ok "[system] role = $ROLE  written to local.cfg"
    else
        log_warn "Could not persist [system] role to local.cfg"
    fi
fi

# ─── 4.5. I2C HAT layout (read-only detection + Imager override) ────────
# Resilience philosophy (chantier 2026-05-28): the detect step OBSERVES
# (it writes hw_layout.json) but never DECIDES. If the bus is unreachable,
# smbus2 is missing, or no HAT is present, this step LOGS the failure and
# moves on — the master/slave services treat hw_layout.json as a dynamic
# reference and will boot in degraded mode rather than crash. Bricking a
# robot because a single PCA9685 is unresponsive is unacceptable.
#
# Order of preference:
#   1. /boot/hw_layout.json (Imager-provided override — wins, no scan)
#   2. scripts/detect_hats.py --output ... (read-only smbus2 scan)
#   3. silent fallback: no JSON written, services will see absence and
#      log a warning at startup (handled in commit 3+, not here)
log "Step 4.5: I2C HAT layout ..."
if [ "$ROLE" = "slave" ]; then
    HW_LAYOUT_OUT="$REPO_PATH/slave/config/hw_layout.json"
else
    HW_LAYOUT_OUT="$REPO_PATH/master/config/hw_layout.json"
fi
mkdir -p "$(dirname "$HW_LAYOUT_OUT")"

BOOT_HW_LAYOUT="$BOOT_DIR/hw_layout.json"
HW_LAYOUT_SOURCE=""

if [ -f "$BOOT_HW_LAYOUT" ]; then
    # Imager-provided override wins — copy it verbatim, no scan.
    if cp "$BOOT_HW_LAYOUT" "$HW_LAYOUT_OUT" 2>>"$LOGFILE"; then
        chmod 0644 "$HW_LAYOUT_OUT" 2>>"$LOGFILE" || true
        chown "$TARGET_USER:$TARGET_USER" "$HW_LAYOUT_OUT" 2>>"$LOGFILE" || true
        HW_LAYOUT_SOURCE="imager-override"
        log_ok "HW layout: Imager-provided $BOOT_HW_LAYOUT → $HW_LAYOUT_OUT"
    else
        log_warn "HW layout: cp $BOOT_HW_LAYOUT failed — falling through to scan"
    fi
fi

if [ -z "$HW_LAYOUT_SOURCE" ]; then
    # Run the read-only detector. Capture rc separately so we can log the
    # specific failure mode (no /dev/i2c-1, no smbus2, bus held by another
    # process) without aborting the boot. The script is GUARANTEED not to
    # write to the I2C bus (ReadOnlySMBus wrapper raises AssertionError on
    # any write attempt + the test suite spies on that contract).
    DETECT_RC=0
    python3 "$REPO_PATH/scripts/detect_hats.py" \
        --output "$HW_LAYOUT_OUT" \
        --role "$ROLE" \
        --verbose 2>&1 | tee -a "$LOGFILE" || DETECT_RC=$?
    if [ "$DETECT_RC" -eq 0 ] && [ -s "$HW_LAYOUT_OUT" ]; then
        chmod 0644 "$HW_LAYOUT_OUT" 2>>"$LOGFILE" || true
        chown "$TARGET_USER:$TARGET_USER" "$HW_LAYOUT_OUT" 2>>"$LOGFILE" || true
        HW_LAYOUT_SOURCE="scan"
        log_ok "HW layout: scan completed → $HW_LAYOUT_OUT"
    else
        # DEGRADED — do NOT abort. Surface the rc so the operator can
        # diagnose via journalctl -u astromech-firstboot.
        # Exit code map (detect_hats.py::main):
        #   2 = smbus2 not installed         3 = /dev/i2c-N missing
        #   4 = permission denied            5 = bus lock held
        case "$DETECT_RC" in
            2) DETAIL="smbus2 not installed (apt install python3-smbus)" ;;
            3) DETAIL="/dev/i2c-1 missing (enable I2C in raspi-config)" ;;
            4) DETAIL="permission denied (user not in i2c group?)" ;;
            5) DETAIL="bus lock held (master.service running?)" ;;
            *) DETAIL="rc=$DETECT_RC, see log above" ;;
        esac
        log_warn "HW layout: detection failed — $DETAIL"
        log_warn "HW layout: services will boot in DEGRADED mode (no hw_layout.json)"
        log_warn "HW layout: review later with: journalctl -u astromech-firstboot"
    fi
fi

# ─── Imager mode detection (shared by §4.6 + §4.7) ─────────────────────
# CONTRACT: this script must be 100% resilient to a "manual install" path
# where the operator just `git pull`s the repo on an existing Pi and runs
# scripts/setup_*.sh by hand — NO Imager pre-bake, NO /boot/astromech_init.cfg.
# Every section below uses `cfg_get section key ""` which returns the empty
# default gracefully if the file is absent (cfg_get tests `[ -f $f ]`
# before reading; see lib_config.sh:64-87). Sections that have nothing to
# do then short-circuit silently — no log_err, no abort, just a single
# `log` line so journalctl tells the truth about what happened.
if [ -f "$INIT_CFG" ]; then
    log_ok "Imager bootstrap detected: $INIT_CFG"
    IMAGER_MODE=1
else
    log "No $INIT_CFG — manual install mode (sections 4.6 + 4.7 will skip)"
    IMAGER_MODE=0
fi

# ─── 4.6. Admin password (Flask UI) ─────────────────────────────────────
# The admin password unlocks the Flask Settings UI; it is ENTIRELY separate
# from the Linux SSH password (per `bd memories admin-password-vs-ssh-separation`).
# Default ships as 'deetoo' in main.cfg. For a fleet Golden-Image deploy at
# a convention, the Imager pre-bakes a random admin password per device in
# astromech_init.cfg [admin] password — this step persists it into local.cfg
# so the running master picks it up at first request. Master role only —
# the slave has no Flask UI.
#
# Manual install fallback: if [admin] password is absent (no Imager OR
# operator opted out), this step is a silent no-op. The Flask UI keeps the
# `deetoo` default from main.cfg, exactly as it does on a manually-cloned
# repo where `setup_master.sh` was run by hand at the prompt.
if [ "$ROLE" = "master" ]; then
    log "Step 4.6: admin password (Flask UI) ..."
    ADMIN_PW=$(cfg_get admin password "")
    if [ -n "$ADMIN_PW" ]; then
        if write_local_cfg admin password "$ADMIN_PW"; then
            log_ok "[admin] password persisted to local.cfg (Imager-baked, len=${#ADMIN_PW})"
        else
            log_warn "Could not write [admin] password to local.cfg — UI stays on the main.cfg default"
        fi
    else
        log "[admin] password not provided — keeping main.cfg default (manual install OK)"
    fi
fi

# ─── 4.7. Hotspot bootstrap + handover (firstboot pairing) ──────────────
# Solves the Golden-Image chicken-and-egg: 20 identical SD cards at a
# convention, each Master/Slave pair must auto-pair without operator typing.
#
# Imager pre-bakes /boot/astromech_init.cfg [hotspot] ssid+password with the
# SAME values on BOTH cards of a paired set (one ssid per PAIR — collision-
# free across robots because the Imager tool generates a unique one per
# burn). Firstboot:
#   Master role → setup_master_network.sh --non-interactive --ssid X --psk Y
#                 creates the bootstrap AP at the pre-baked SSID.
#                 Then waits up to 5 min for the Slave to associate, regen-
#                 erates a FINAL serial-derived SSID via gen_hotspot_ssid.sh,
#                 pushes new creds to Slave over SSH (replicates Flask's
#                 _push_slave_hotspot_creds), then switches its own AP to
#                 the FINAL SSID. Pair is sealed for life.
#   Slave  role → setup_slave_network.sh --non-interactive --ssid X --psk Y
#                 joins the bootstrap AP. The Master rewrites this profile
#                 over SSH a few seconds later — the Slave's autoconnect
#                 transparently rejoins the FINAL SSID on the next master
#                 AP cycle.
#
# Skipped silently if [hotspot] is missing from astromech_init.cfg
# (operator opted out of auto-pairing — they will run setup_*_network.sh
# manually later).
#
# Manual install fallback: if [hotspot] is missing from astromech_init.cfg
# (no Imager, or operator opted out), this section is a SILENT no-op. The
# operator is expected to run scripts/setup_master_network.sh and
# scripts/setup_slave_network.sh BY HAND at the interactive prompts (the
# scripts preserve their full interactive mode when `--non-interactive`
# is NOT passed). This keeps the "git pull + bash setup_*.sh" workflow
# 100% functional alongside the Imager-driven Golden Image path.
log "Step 4.7: hotspot bootstrap + handover ..."
BOOT_SSID=$(cfg_get hotspot ssid "")
BOOT_PSK=$(cfg_get hotspot password "")

if [ -z "$BOOT_SSID" ] || [ -z "$BOOT_PSK" ]; then
    log "Hotspot bootstrap skipped: no [hotspot] in astromech_init.cfg (manual install — operator will run setup_*_network.sh by hand)"
elif [ "${#BOOT_PSK}" -lt 8 ]; then
    log_err "Hotspot bootstrap skipped: [hotspot] password <8 chars (WPA min)"
elif [ "$ROLE" = "master" ]; then
    log "Master path: bootstrap SSID='$BOOT_SSID' → unique final SSID after slave joins"

    # 1) Create bootstrap AP on wlan0 (non-interactive). The script also
    #    migrates wlan0's home WiFi to wlan1 if a USB dongle is plugged in
    #    AND wlan0 already had a known connection — otherwise it skips
    #    that step gracefully (Imager image may not have wlan1 yet).
    if bash "$REPO_PATH/scripts/setup_master_network.sh" \
            --non-interactive --ssid "$BOOT_SSID" --psk "$BOOT_PSK" 2>&1 \
            | tee -a "$LOGFILE"; then
        log_ok "Bootstrap AP up on wlan0 (SSID='$BOOT_SSID')"
    else
        log_err "setup_master_network.sh failed — leaving network alone"
        # Fall through; do not abort firstboot. Operator can run manually.
        BOOT_SSID=""   # disables handover below
    fi

    if [ -n "$BOOT_SSID" ]; then
        # 2) Wait for the Slave to join the bootstrap AP. Resolve via
        #    avahi (.local) since the slave sets its hostname during its
        #    own firstboot (§4 above) and avahi is installed by the
        #    network setup scripts. SSH probe confirms key-based auth
        #    works — without it, the cred push at step 4 cannot run.
        SLAVE_TARGET=$(cfg_get slave host "astromech-slave.local")
        SSH_USER=$(cfg_get slave user "$TARGET_USER")
        log "Waiting up to 5 min for Slave at $SSH_USER@$SLAVE_TARGET ..."
        TIMEOUT_S=300
        SLAVE_OK=0
        WAIT_START=$SECONDS
        while [ $((SECONDS - WAIT_START)) -lt "$TIMEOUT_S" ]; do
            if ping -c 1 -W 2 "$SLAVE_TARGET" >/dev/null 2>&1 \
                && ssh -o StrictHostKeyChecking=accept-new \
                        -o BatchMode=yes \
                        -o ConnectTimeout=4 \
                        "$SSH_USER@$SLAVE_TARGET" 'true' >/dev/null 2>&1; then
                SLAVE_OK=1
                break
            fi
            sleep 5
        done

        if [ "$SLAVE_OK" -ne 1 ]; then
            log_warn "Slave not reachable after 5 min — leaving AP on bootstrap SSID."
            log_warn "Operator can finish the pairing later via Flask UI → Settings → Hotspot."
        else
            log_ok "Slave reachable — proceeding with handover"

            # 3) Generate the per-robot final SSID from /proc/cpuinfo serial.
            FINAL_SSID=$(bash "$REPO_PATH/scripts/gen_hotspot_ssid.sh" 2>/dev/null || echo "")
            FINAL_PSK="$BOOT_PSK"   # keep PSK as-is for simplicity; operator can change later via UI
            if [ -z "$FINAL_SSID" ] || [ "$FINAL_SSID" = "$BOOT_SSID" ]; then
                log_warn "gen_hotspot_ssid produced empty/same SSID — keeping bootstrap SSID"
            else
                log "Final SSID='$FINAL_SSID' — pushing to Slave first (mirrors _push_slave_hotspot_creds)"

                # 4) Push final creds to the Slave's nmcli profile FIRST.
                #    Slave profile name resolves on the slave (prefer new
                #    astromech-master-hotspot, fall back to legacy
                #    r2d2-master-hotspot). nmcli modify rewrites the
                #    stored profile WITHOUT dropping the live connection;
                #    slave only reconnects after Master flips its own AP.
                _NEW_CON='astromech-master-hotspot'
                _LEG_CON='r2d2-master-hotspot'
                _PICK="CON=\$(nmcli -t -f NAME connection show 2>/dev/null | grep -Fxq '$_NEW_CON' && echo $_NEW_CON || echo $_LEG_CON)"
                _PUSH="$_PICK; sudo -n nmcli connection modify \"\$CON\" 802-11-wireless.ssid '$FINAL_SSID' wifi-sec.psk '$FINAL_PSK'"
                if ssh -o StrictHostKeyChecking=accept-new \
                       -o BatchMode=yes \
                       -o ConnectTimeout=6 \
                       "$SSH_USER@$SLAVE_TARGET" "$_PUSH" 2>>"$LOGFILE"; then
                    log_ok "Slave profile updated with final creds"

                    # 5) Now flip the Master's own AP to the final SSID.
                    #    Slave's NM auto-reconnects to the new SSID (its
                    #    profile points at it now).
                    if nmcli connection modify astromech-hotspot \
                            802-11-wireless.ssid "$FINAL_SSID" \
                            wifi-sec.psk "$FINAL_PSK" 2>>"$LOGFILE" \
                       && nmcli connection up astromech-hotspot 2>>"$LOGFILE"; then
                        log_ok "Master AP switched to FINAL SSID='$FINAL_SSID' — pair sealed"

                        # 6) Persist the final creds in local.cfg [hotspot].
                        #    Re-uses setup_master_network.sh's cfg_set semantics
                        #    via a minimal sed pass — keeps the file format
                        #    unchanged for the Flask UI.
                        LOCAL_CFG_PATH="$REPO_PATH/master/config/local.cfg"
                        if [ -f "$LOCAL_CFG_PATH" ]; then
                            sed -i \
                                -e "/^\[hotspot\]/,/^\[/ s|^ssid\s*=.*|ssid = $FINAL_SSID|" \
                                -e "/^\[hotspot\]/,/^\[/ s|^password\s*=.*|password = $FINAL_PSK|" \
                                "$LOCAL_CFG_PATH" 2>>"$LOGFILE" \
                                && log_ok "local.cfg [hotspot] updated with final SSID" \
                                || log_warn "Could not update local.cfg [hotspot]"
                            chown "$TARGET_USER:$TARGET_USER" "$LOCAL_CFG_PATH" 2>/dev/null || true
                        fi
                    else
                        log_err "Master AP flip to final SSID failed — pair stays on bootstrap"
                    fi
                else
                    log_err "SSH push to Slave failed — keeping bootstrap SSID on Master"
                fi
            fi
        fi
    fi

elif [ "$ROLE" = "slave" ]; then
    log "Slave path: joining bootstrap AP '$BOOT_SSID' (Master will rewrite our profile after handover)"
    if bash "$REPO_PATH/scripts/setup_slave_network.sh" \
            --non-interactive --ssid "$BOOT_SSID" --psk "$BOOT_PSK" 2>&1 \
            | tee -a "$LOGFILE"; then
        log_ok "Slave joined bootstrap AP — Master will push final SSID over SSH shortly"
    else
        log_err "setup_slave_network.sh failed — slave will be unpaired"
    fi
fi

# ─── 5. DNA-validate + switch origin if a custom repo URL is set ────────
# Reads [github] repo_url from /boot/astromech_init.cfg first (the Imager's
# choice), falls back to local.cfg if already populated. Only swaps origin
# if validate_paternity passes.
CANDIDATE_URL=$(cfg_get github repo_url "")
CANDIDATE_BRANCH=$(cfg_get github branch "main")

if [ -n "$CANDIDATE_URL" ] && [ -d "$REPO_PATH/.git" ]; then
    # Find current origin URL (best effort — git remote in a freshly-imaged
    # repo may or may not be set yet)
    CURRENT_ORIGIN=$(git -C "$REPO_PATH" remote get-url origin 2>/dev/null || echo "")
    if [ "$CANDIDATE_URL" != "$CURRENT_ORIGIN" ]; then
        log "DNA validating candidate repo_url='$CANDIDATE_URL' branch='$CANDIDATE_BRANCH' ..."
        if dna_validate "$CANDIDATE_URL" "$CANDIDATE_BRANCH" 2>&1 | tee -a "$LOGFILE"; then
            log_ok "DNA OK — switching origin to $CANDIDATE_URL"
            git -C "$REPO_PATH" remote set-url origin "$CANDIDATE_URL"
            git -C "$REPO_PATH" fetch --no-tags origin "$CANDIDATE_BRANCH" \
                && git -C "$REPO_PATH" reset --hard "origin/$CANDIDATE_BRANCH" \
                && log_ok "Aligned to origin/$CANDIDATE_BRANCH" \
                || log_err "fetch+reset failed; origin URL still updated but tree not reset"
        else
            log_err "DNA FAIL — keeping origin pointed at: $CURRENT_ORIGIN"
            log_err "Candidate URL '$CANDIDATE_URL' is NOT a fork of RickDnamps/AstromechOS"
        fi
    else
        log_ok "github.repo_url matches current origin — no switch needed"
    fi
else
    log "Skipping repo switch: candidate='$CANDIDATE_URL' .git present=$([ -d "$REPO_PATH/.git" ] && echo y || echo n)"
fi

# ─── 6. Self-destruct + reboot ──────────────────────────────────────────
log "Cleaning up first-boot artefacts ..."

# Delete the secrets directory. Best-effort `shred` for the private key
# before unlinking, then rm -rf the parent dir.
if [ -d "$SECRETS_DIR" ]; then
    for f in "$SECRETS_DIR"/id_* "$SECRETS_DIR"/authorized_keys; do
        [ -f "$f" ] && shred -u "$f" 2>/dev/null || rm -f "$f" 2>/dev/null || true
    done
    rm -rf "$SECRETS_DIR" 2>/dev/null && log_ok "Secrets directory wiped" \
        || log_warn "Could not fully remove $SECRETS_DIR — check /boot perms"
fi

# Delete the trigger LAST — if anything above failed catastrophically the
# operator can re-trigger by re-creating the marker.
rm -f "$TRIGGER" && log_ok "Trigger marker deleted ($TRIGGER)" \
    || log_err "Could not delete trigger $TRIGGER — script will re-run on next boot"

# Also disable our own systemd unit so it doesn't even try next boot.
systemctl disable astromech-firstboot.service 2>/dev/null || true

sync
log_ok "First-boot provisioning complete — rebooting in 5s"
log "=========================================="
sleep 5
reboot
