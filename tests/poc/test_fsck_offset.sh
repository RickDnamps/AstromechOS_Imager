#!/bin/bash
F=/tmp/sd_combo.img
OFF=17825792

echo "=== Try e2fsck with -E offset= ==="
e2fsck -fn -E "offset=$OFF" "$F" 2>&1 | tail -7
echo ""
echo "=== Try e2fsck with image?offset=N syntax ==="
e2fsck -fn "${F}?offset=${OFF}" 2>&1 | tail -7
echo ""
echo "=== Confirm mutations persist via re-read ==="
debugfs -R "cat /etc/passwd" "${F}?offset=${OFF}" 2>&1 | grep -v "^debugfs"
echo ""
echo "=== rename via offset ==="
cat > /tmp/r2.txt <<EOF
link /home/artoo /home/pi
unlink /home/artoo
quit
EOF
debugfs -w -f /tmp/r2.txt "${F}?offset=${OFF}" 2>&1 | tail -3
echo "After:"
debugfs -R "ls /home" "${F}?offset=${OFF}" 2>&1 | tail -3
echo ""
echo "=== Final e2fsck ==="
e2fsck -fn "${F}?offset=${OFF}" 2>&1 | tail -3
