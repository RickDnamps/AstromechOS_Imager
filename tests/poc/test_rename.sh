#!/bin/bash
# POC: directory rename via debugfs link + unlink
set -e
F="$1"
[ -z "$F" ] || [ ! -f "$F" ] && { echo "usage: $0 fixture.img"; exit 1; }

echo "=== BEFORE rename: ls /home ==="
debugfs -R 'ls -l /home' "$F" 2>&1 | tail -5

echo ""
echo "=== Inode of /home/pi BEFORE ==="
debugfs -R 'stat /home/pi' "$F" 2>&1 | grep -E "^Inode|^Generation|^Links|^Size" | head -4

echo ""
echo "=== ATTEMPT 1: link /home/pi /home/artoo, then unlink /home/pi ==="
cat > /tmp/rename.txt <<'EOF'
link /home/pi /home/artoo
unlink /home/pi
quit
EOF
debugfs -w -f /tmp/rename.txt "$F" 2>&1 | tail -5

echo ""
echo "=== AFTER rename: ls /home ==="
debugfs -R 'ls -l /home' "$F" 2>&1 | tail -5

echo ""
echo "=== Inode of /home/artoo AFTER (should match BEFORE inode of /home/pi) ==="
debugfs -R 'stat /home/artoo' "$F" 2>&1 | grep -E "^Inode|^Generation|^Links|^Size" | head -4

echo ""
echo "=== Files inside /home/artoo (should contain welcome.txt) ==="
debugfs -R 'ls -l /home/artoo' "$F" 2>&1 | tail -5

echo ""
echo "=== e2fsck after rename ==="
e2fsck -fn "$F" 2>&1 | tail -8
