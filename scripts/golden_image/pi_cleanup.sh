#!/bin/bash
# pi_cleanup.sh — Cleanup a Pi 4B for Golden Image dd extraction.
#
# Runs ON THE Pi (master OR slave) as root. Stops the AstromechOS
# service, plus avahi/bluetooth/ModemManager to free RAM, then clears
# ephemeral state (logs, journal, apt cache, /tmp, bash history) so the
# resulting dd produces a maximally-clean rootfs for the Golden Image.
#
# After cleanup, mounts /dev/sda1 (the USB SSD) at /mnt/ssd ready for
# the dd command.
#
# Usage:
#     sudo bash pi_cleanup.sh master    # on master Pi
#     sudo bash pi_cleanup.sh slave     # on slave Pi
#
# See docs/GOLDEN_IMAGE_BUILD.md for the full workflow.

set +e  # don't abort on best-effort cleanup steps

# ── Parse role argument ───────────────────────────────────────────────
ROLE="${1:-}"
if [[ "$ROLE" != "master" && "$ROLE" != "slave" ]]; then
    echo "ERROR: role must be 'master' or 'slave'"
    echo "Usage: sudo bash $0 master|slave"
    exit 1
fi

SERVICE="astromech-${ROLE}.service"
echo "=== pi_cleanup.sh role=${ROLE} (service=${SERVICE}) ==="

# ── Pre-state report ──────────────────────────────────────────────────
echo ""
echo "--- BEFORE: disk usage ---"
df -h /

# ── Stop services ─────────────────────────────────────────────────────
echo ""
echo "--- Stopping services ---"
systemctl stop "$SERVICE" 2>/dev/null && echo "  $SERVICE stopped"
systemctl stop avahi-daemon 2>/dev/null && echo "  avahi-daemon stopped"
systemctl stop bluetooth 2>/dev/null && echo "  bluetooth stopped"
systemctl stop ModemManager 2>/dev/null && echo "  ModemManager stopped"

# ── Truncate /var/log/*.log ───────────────────────────────────────────
echo ""
echo "--- Truncating /var/log/*.log ---"
find /var/log -type f -name '*.log' -exec truncate -s 0 {} + 2>/dev/null
find /var/log -type f \( -name '*.gz' -o -name '*.1' -o -name '*.old' \
                       -o -name '*.2' -o -name '*.3' \) -delete 2>/dev/null
echo "  logs truncated, rotated logs deleted"

# ── Vacuum systemd journal ────────────────────────────────────────────
echo ""
echo "--- Vacuuming systemd journal to 1 MB ---"
journalctl --vacuum-size=1M 2>&1 | tail -3

# ── Clear APT cache ───────────────────────────────────────────────────
echo ""
echo "--- Clearing APT cache ---"
apt-get clean 2>&1 | tail -1
apt-get autoclean 2>&1 | tail -1

# ── Clear /tmp + /var/tmp ─────────────────────────────────────────────
echo ""
echo "--- Clearing /tmp + /var/tmp ---"
rm -rf /tmp/* /tmp/.[!.]* 2>/dev/null
rm -rf /var/tmp/* /var/tmp/.[!.]* 2>/dev/null
echo "  tmp dirs cleared"

# ── Clear bash histories ──────────────────────────────────────────────
echo ""
echo "--- Clearing bash histories ---"
for h in /home/*/.bash_history /root/.bash_history; do
    if [ -f "$h" ]; then
        : > "$h" && echo "  cleared $h"
    fi
done

# ── Mount USB SSD ─────────────────────────────────────────────────────
echo ""
echo "--- Mounting USB SSD at /mnt/ssd ---"
mkdir -p /mnt/ssd
umount /mnt/ssd 2>/dev/null
if mount /dev/sda1 /mnt/ssd; then
    echo "  SSD mounted"
    df -h /mnt/ssd
else
    echo "  ERROR: failed to mount /dev/sda1. Is the SSD plugged in?"
    echo "  USB devices:"
    lsusb | head -5
    exit 1
fi

# ── Sync + drop kernel caches ─────────────────────────────────────────
echo ""
echo "--- Sync + drop kernel caches ---"
sync
echo 3 > /proc/sys/vm/drop_caches
echo "  done"

# ── Post-state report ─────────────────────────────────────────────────
echo ""
echo "--- AFTER: disk + RAM ---"
df -h /
free -m | head -2

echo ""
echo "=== Ready for dd. Next step (paste in this SSH session): ==="
echo ""
echo "  echo deetoo | sudo -S sh -c 'sync; dd if=/dev/mmcblk0 of=/mnt/ssd/${ROLE}_golden.img bs=4M status=progress conv=fdatasync; sync; ls -la /mnt/ssd/${ROLE}_golden.img'"
echo ""
echo "  When dd completes, unmount with:"
echo "  echo deetoo | sudo -S sh -c 'sync; umount /mnt/ssd && echo SSD_UNMOUNTED_CLEAN'"
