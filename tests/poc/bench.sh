#!/bin/bash
set -e
F="$1"
echo "=== BENCH: 50 mutation cycles ==="
cp "$F" /tmp/bench.img
# Pre-populate /tmp/passwd_new from the fixture (avoid setup outside the loop)
cat > /tmp/passwd_new <<'EOF'
root:x:0:0:root:/root:/bin/bash
testuser:x:1000:1000:,,,:/home/testuser:/bin/bash
EOF
# pre-state needed: /home/testuser (from prior rename POC); reset to /home/pi if needed
debugfs -R 'ls /home' /tmp/bench.img > /tmp/state 2>&1
if grep -q testuser /tmp/state; then
  CURRENT=testuser
  OTHER=pi
else
  CURRENT=pi
  OTHER=testuser
fi
echo "Start state: /home/$CURRENT exists"

START=$(date +%s%N)
for i in $(seq 1 50); do
  cat > /tmp/cycle.txt <<EOF
rm /etc/passwd
write /tmp/passwd_new /etc/passwd
link /home/$CURRENT /home/$OTHER
unlink /home/$CURRENT
quit
EOF
  debugfs -w -f /tmp/cycle.txt /tmp/bench.img >/dev/null 2>&1
  # swap roles for next cycle
  TMP=$CURRENT; CURRENT=$OTHER; OTHER=$TMP
done
END=$(date +%s%N)
ELAPSED=$((END - START))
MS=$((ELAPSED / 1000000))
AVG=$((MS / 50))
echo "50 cycles = ${MS} ms total = ${AVG} ms/cycle avg"
echo ""

echo "=== e2fsck after 50 cycles ==="
e2fsck -fn /tmp/bench.img 2>&1 | tail -3

echo ""
echo "=== Binary footprint ==="
ls -la /usr/sbin/debugfs /usr/sbin/e2fsck /usr/sbin/mke2fs 2>&1
echo ""
echo "=== debugfs deps count + key libs ==="
ldd /usr/sbin/debugfs | wc -l
ldd /usr/sbin/debugfs | grep -iE "libext2|libcom_err|libe2p" || true
