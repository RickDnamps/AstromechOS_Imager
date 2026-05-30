#!/bin/bash
# POC: can debugfs operate on a partition inside an SD image via offset?
set -e

# Build a 96 MB combined image: 16 MB FAT32 boot + 80 MB ext4 rootfs
COMBO=/tmp/sd_combo.img
EXT4_SRC="$1"
[ -f "$EXT4_SRC" ] || { echo "usage: $0 fixture.ext4.img"; exit 1; }

echo "=== Build combined SD-shaped image ==="
SECTOR=512
BOOT_START_SECTOR=2048               # 1 MB align
BOOT_SIZE_SECTORS=$((16 * 1024 * 1024 / SECTOR))  # 16 MB
ROOTFS_START_SECTOR=$((BOOT_START_SECTOR + BOOT_SIZE_SECTORS))
ROOTFS_BYTES=$((80 * 1024 * 1024))
TOTAL_BYTES=$(($((ROOTFS_START_SECTOR * SECTOR)) + ROOTFS_BYTES))

dd if=/dev/zero of=$COMBO bs=1M count=$((TOTAL_BYTES / 1024 / 1024 + 1)) status=none
# MBR with FAT32 (type 0x0C) at sector 2048, ext4 (type 0x83) at sector 34816
printf '\x55\xAA' | dd of=$COMBO bs=1 seek=510 count=2 conv=notrunc status=none

# Partition 1 entry @446: type=0x0C, LBA start=2048, LBA size=BOOT_SIZE_SECTORS
printf '\x00\x00\x00\x00\x0C\x00\x00\x00' | dd of=$COMBO bs=1 seek=446 conv=notrunc status=none
printf '\x00\x08\x00\x00' | dd of=$COMBO bs=1 seek=454 conv=notrunc status=none  # 2048
SIZE_LE=$(printf '%08x' $BOOT_SIZE_SECTORS | sed 's/\(..\)\(..\)\(..\)\(..\)/\\x\4\\x\3\\x\2\\x\1/')
printf "$SIZE_LE" | dd of=$COMBO bs=1 seek=458 conv=notrunc status=none

# Partition 2 entry @462: type=0x83, LBA start=ROOTFS_START_SECTOR, LBA size=...
printf '\x00\x00\x00\x00\x83\x00\x00\x00' | dd of=$COMBO bs=1 seek=462 conv=notrunc status=none
START_LE=$(printf '%08x' $ROOTFS_START_SECTOR | sed 's/\(..\)\(..\)\(..\)\(..\)/\\x\4\\x\3\\x\2\\x\1/')
printf "$START_LE" | dd of=$COMBO bs=1 seek=470 conv=notrunc status=none
ROOTFS_SIZE_SECTORS=$((ROOTFS_BYTES / SECTOR))
RSIZE_LE=$(printf '%08x' $ROOTFS_SIZE_SECTORS | sed 's/\(..\)\(..\)\(..\)\(..\)/\\x\4\\x\3\\x\2\\x\1/')
printf "$RSIZE_LE" | dd of=$COMBO bs=1 seek=474 conv=notrunc status=none

# Copy the ext4 fixture content into the rootfs partition slot
dd if="$EXT4_SRC" of=$COMBO bs=1M seek=$((ROOTFS_START_SECTOR * SECTOR / 1024 / 1024)) conv=notrunc status=none

ROOTFS_OFFSET=$((ROOTFS_START_SECTOR * SECTOR))
echo "Combined image built: $(ls -la $COMBO | awk '{print $5}') bytes"
echo "Rootfs partition starts at byte offset: $ROOTFS_OFFSET"
echo ""

echo "=== TEST: debugfs with ?offset=N on combined image ==="
debugfs -R 'ls /home' "$COMBO?offset=$ROOTFS_OFFSET" 2>&1 | tail -5
echo ""

echo "=== TEST: write mutation via offset ==="
cat > /tmp/passwd_new <<'EOF'
root:x:0:0:root:/root:/bin/bash
testuser:x:1000:1000:,,,:/home/testuser:/bin/bash
EOF
cat > /tmp/mut.txt <<EOF
rm /etc/passwd
write /tmp/passwd_new /etc/passwd
quit
EOF
debugfs -w -f /tmp/mut.txt "$COMBO?offset=$ROOTFS_OFFSET" 2>&1 | tail -3

echo "=== Verify after offset mutation ==="
debugfs -R 'cat /etc/passwd' "$COMBO?offset=$ROOTFS_OFFSET" 2>&1 | tail -3
echo ""

echo "=== e2fsck via offset ==="
e2fsck -fn -E offset=$ROOTFS_OFFSET "$COMBO" 2>&1 | tail -5
