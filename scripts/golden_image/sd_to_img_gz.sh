#!/bin/bash
# sd_to_img_gz.sh — One-shot SD card → Golden Image pipeline (WSL Debian root).
#
# Runs INSIDE WSL Debian AS ROOT. The SD card must already be mounted via
# `wsl --mount \\.\PHYSICALDRIVE<N> --bare -d Debian` (PowerShell admin).
#
# Steps:
#   1. Auto-detect USB block device (the SD via Windows mount-bind)
#   2. DD raw SD card → /tmp/raw.img
#   3. pishrink -a raw.img (auto resize + inject firstboot resize)
#   4. gzip → /mnt/j/R2-D2_Build/images/AstromechOS_<Role>_<DD-MM-YYYY>.img.gz
#   5. sha256sum → matching .sha256 sidecar
#   6. Cleanup /tmp/raw.img
#
# Usage:
#   wsl -d Debian -u root bash /mnt/j/R2-D2_Build/AstroMechOS_Imager/scripts/golden_image/sd_to_img_gz.sh master
#   wsl -d Debian -u root bash /mnt/j/R2-D2_Build/AstroMechOS_Imager/scripts/golden_image/sd_to_img_gz.sh slave
#
# Optional 2nd arg: override the date (default = today DD-MM-YYYY).
set -euo pipefail

ROLE="${1:-}"
DATE_ARG="${2:-$(date +%d-%m-%Y)}"

if [[ "$ROLE" != "master" && "$ROLE" != "slave" ]]; then
    echo "ERROR: arg 1 must be 'master' or 'slave' (got: '$ROLE')"
    exit 1
fi

# Capitalize role for filename (master → Master)
ROLE_CAP="$(tr '[:lower:]' '[:upper:]' <<< "${ROLE:0:1}")${ROLE:1}"
OUT_DIR="/mnt/j/R2-D2_Build/images"
OUT_NAME="AstromechOS_${ROLE_CAP}_${DATE_ARG}.img.gz"
OUT_PATH="${OUT_DIR}/${OUT_NAME}"

echo "=== sd_to_img_gz.sh role=${ROLE} date=${DATE_ARG} ==="
echo "Target: ${OUT_PATH}"

# ── 1. Auto-detect the USB SD device ────────────────────────────────
echo ""
echo "--- [1/6] Detecting USB SD device ---"
SDDEV="$(lsblk -dpno NAME,TRAN | awk '$2=="usb"{print $1; exit}')"
if [[ -z "$SDDEV" ]]; then
    echo "ERROR: no USB block device found via lsblk."
    echo "       Run 'wsl --mount \\.\\PHYSICALDRIVE<N> --bare -d Debian' from"
    echo "       PowerShell admin first, then re-run this script."
    echo ""
    echo "Current block devices:"
    lsblk -o NAME,SIZE,MODEL,TRAN
    exit 1
fi
SD_SIZE_GB="$(lsblk -bdno SIZE "$SDDEV" | awk '{printf "%.1f", $1/1073741824}')"
echo "  SD device: ${SDDEV} (${SD_SIZE_GB} GB)"

# Sanity check — refuse to DD a very large device (>128 GB ≈ definitely not an SD)
SD_SIZE_BYTES="$(lsblk -bdno SIZE "$SDDEV")"
MAX_SD_BYTES=$((128 * 1024 * 1024 * 1024))
if (( SD_SIZE_BYTES > MAX_SD_BYTES )); then
    echo "ERROR: device ${SDDEV} is ${SD_SIZE_GB} GB — too large to be an SD card."
    echo "       Aborting as a safety measure. Verify wsl --mount target."
    exit 1
fi

# ── 2. DD raw → /tmp/raw.img ────────────────────────────────────────
echo ""
echo "--- [2/6] dd ${SDDEV} → /tmp/raw.img (status=progress) ---"
cd /tmp
rm -f raw.img
dd if="${SDDEV}" of=raw.img bs=4M status=progress conv=fsync

# ── 3. pishrink (install if missing) ────────────────────────────────
echo ""
echo "--- [3/6] pishrink -a raw.img ---"
if ! command -v pishrink.sh >/dev/null 2>&1; then
    echo "  pishrink not found — installing..."
    if ! command -v curl >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y curl
    fi
    curl -sLo /usr/local/bin/pishrink.sh \
        https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh
    chmod +x /usr/local/bin/pishrink.sh
fi
pishrink.sh -a /tmp/raw.img

# ── 4. gzip → final path ────────────────────────────────────────────
echo ""
echo "--- [4/6] gzip → ${OUT_PATH} ---"
mkdir -p "${OUT_DIR}"
# pigz is parallel — install if available
if command -v pigz >/dev/null 2>&1; then
    pigz -c /tmp/raw.img > "${OUT_PATH}"
else
    gzip -c /tmp/raw.img > "${OUT_PATH}"
fi
echo "  Wrote $(stat -c %s "${OUT_PATH}") bytes"

# ── 5. sha256sum sidecar ────────────────────────────────────────────
echo ""
echo "--- [5/6] sha256sum sidecar ---"
cd "${OUT_DIR}"
sha256sum "${OUT_NAME}" > "${OUT_NAME}.sha256"
cat "${OUT_NAME}.sha256"
# Verify
sha256sum -c "${OUT_NAME}.sha256"
echo "  Sidecar verified ✓"

# ── 6. Cleanup ──────────────────────────────────────────────────────
echo ""
echo "--- [6/6] Cleanup /tmp/raw.img ---"
rm -f /tmp/raw.img

echo ""
echo "=== ✅ DONE ==="
echo "Image  : ${OUT_PATH}"
echo "Sidecar: ${OUT_PATH}.sha256"
echo ""
echo "Now from PowerShell admin:  wsl --unmount \\.\PHYSICALDRIVE<N>"
