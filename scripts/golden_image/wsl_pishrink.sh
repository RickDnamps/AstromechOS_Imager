#!/bin/bash
# wsl_pishrink.sh — Pishrink a Golden Image inside WSL2 Debian.
#
# Runs ON THE PC IN WSL2 DEBIAN (as root). Auto-mounts the USB SSD
# (assumed to be Windows drive K:), auto-installs pigz + pishrink if
# missing, then runs pishrink with the canonical AstroMechOS_Imager
# flags:
#     -a : parallel pigz compression (all CPU cores)
#     -z : gzip output (.img.gz)
#   NO -s : keep pishrink's autoexpand -- it grows the ext4 FILESYSTEM to
#           fill the card on first boot. The Imager's cmdline 'resize' token
#           only grows the PARTITION, not the FS; an early build wrongly used
#           -s and shipped a full partition with an un-grown ext4 (wasted space).
#
# Input image must be at /mnt/k/<filename>. Output replaces the .img
# with .img.gz at the same path.
#
# Usage:
#     wsl --shutdown                         # PowerShell, if K: was just plugged
#     wsl -d Debian -u root -- bash wsl_pishrink.sh master_golden.img
#     wsl -d Debian -u root -- bash wsl_pishrink.sh slave_golden.img
#
# See docs/GOLDEN_IMAGE_BUILD.md for the full workflow.

set -e

# ── Parse filename argument ───────────────────────────────────────────
FILENAME="${1:-}"
if [[ -z "$FILENAME" ]]; then
    echo "ERROR: image filename required"
    echo "Usage: bash wsl_pishrink.sh <filename.img>"
    echo "  e.g. bash wsl_pishrink.sh master_golden.img"
    exit 1
fi
IMG="/mnt/k/${FILENAME}"

echo "=== wsl_pishrink.sh ${FILENAME} ==="

# ── Auto-mount K: if needed ───────────────────────────────────────────
if [ ! -d /mnt/k ]; then
    echo ""
    echo "--- /mnt/k missing, creating + mounting ---"
    mkdir -p /mnt/k
fi
if ! mountpoint -q /mnt/k 2>/dev/null; then
    echo "--- Mounting K: as drvfs ---"
    if ! mount -t drvfs K: /mnt/k; then
        echo "ERROR: failed to mount K:."
        echo "       Run 'wsl --shutdown' from PowerShell, then re-run this script."
        echo "       (WSL2 only auto-mounts drives present at startup.)"
        exit 1
    fi
    echo "  K: mounted at /mnt/k"
fi

if [ ! -f "$IMG" ]; then
    echo ""
    echo "ERROR: $IMG not found"
    echo "Contents of /mnt/k:"
    ls -la /mnt/k/ 2>&1 | head -10
    exit 1
fi

echo ""
echo "--- Source image ---"
ls -la "$IMG"

# ── Install pigz if missing (used by -a flag for parallel gzip) ───────
if ! command -v pigz >/dev/null 2>&1; then
    echo ""
    echo "--- Installing pigz ---"
    apt-get update -qq 2>&1 | tail -3
    apt-get install -y pigz 2>&1 | tail -3
fi

# ── Install curl or wget for pishrink download ────────────────────────
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    echo ""
    echo "--- Installing curl ---"
    apt-get install -y curl 2>&1 | tail -3
fi

# ── Install pishrink if missing ───────────────────────────────────────
if [ ! -x /usr/local/bin/pishrink ]; then
    echo ""
    echo "--- Installing pishrink from GitHub ---"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh \
            -o /usr/local/bin/pishrink
    else
        wget -q https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh \
            -O /usr/local/bin/pishrink
    fi
    chmod +x /usr/local/bin/pishrink
fi
echo ""
echo "--- Tools ---"
echo "  pigz:     $(which pigz)"
echo "  pishrink: $(which pishrink)"
echo "  Dependencies: $(which parted e2fsck resize2fs dumpe2fs losetup tune2fs | tr '\n' ' ')"

# ── Run pishrink ──────────────────────────────────────────────────────
echo ""
echo "=== Running pishrink -a -z on ${FILENAME} ==="
echo "    -a : parallel pigz compression (all cores)"
echo "    -z : gzip output (.img.gz)"
echo "    NO -s : keep pishrink's autoexpand -- it is what grows the ext4"
echo "            FILESYSTEM to fill the card on first boot. The Imager's"
echo "            cmdline 'resize' token only grows the PARTITION, not the"
echo "            filesystem; an early build wrongly used -s and shipped a"
echo "            full-size partition with an un-grown ext4 (wasted space)."
echo ""
echo "  Expected steps: e2fsck → resize2fs → parted shrink → truncate"
echo "                  → pigz parallel compress"
echo "  ETA: ~5-15 min depending on image size"
echo ""

pishrink -a -z "$IMG"

# ── Report final ──────────────────────────────────────────────────────
echo ""
echo "=== Final files on K: ==="
ls -la "/mnt/k/${FILENAME}"* 2>/dev/null

echo ""
echo "=== Summary ==="
GZIMG="${IMG}.gz"
if [ -f "$GZIMG" ]; then
    SZ=$(stat -c %s "$GZIMG")
    echo "  Final: $GZIMG"
    echo "  Size:  $(numfmt --to=iec-i --suffix=B $SZ) ($SZ bytes)"
    echo ""
    echo "  Next steps (PowerShell):"
    echo "    Copy-Item \"$GZIMG\" \"J:\\R2-D2_Build\\images\\AstromechOS__<Role>_<date>.img.gz\""
    echo "    sha256sum AstromechOS__<Role>_<date>.img.gz > AstromechOS__<Role>_<date>.img.gz.sha256"
else
    echo "  ERROR: $GZIMG not produced. Check pishrink output above."
    exit 1
fi
