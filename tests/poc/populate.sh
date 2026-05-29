#!/bin/bash
# POC fixture populator — runs in WSL
set -e

F="$1"
[ -z "$F" ] && { echo "usage: $0 fixture.img"; exit 1; }
[ -f "$F" ] || { echo "no such file: $F"; exit 1; }

echo "== Stage 1: populate fixture via debugfs =="

# Prepare host-side source files
cat > /tmp/passwd <<'EOF'
root:x:0:0:root:/root:/bin/bash
pi:x:1000:1000:,,,:/home/pi:/bin/bash
EOF
cat > /tmp/shadow <<'EOF'
root:*:19000:0:99999:7:::
pi:DUMMYHASH:19000:0:99999:7:::
EOF
cat > /tmp/group <<'EOF'
root:x:0:
pi:x:1000:
EOF
echo "hello from pi" > /tmp/welcome.txt

# Write debugfs command script
cat > /tmp/cmds.txt <<'EOF'
mkdir /etc
mkdir /home
mkdir /home/pi
write /tmp/passwd /etc/passwd
write /tmp/shadow /etc/shadow
write /tmp/group /etc/group
write /tmp/welcome.txt /home/pi/welcome.txt
quit
EOF

debugfs -w -f /tmp/cmds.txt "$F" 2>&1

echo "== Stage 2: verify =="
debugfs -R "ls -l /etc" "$F" 2>&1
echo "---"
debugfs -R "ls -l /home" "$F" 2>&1
echo "---"
debugfs -R "cat /etc/passwd" "$F" 2>&1
echo "---"
e2fsck -fn "$F" 2>&1 | tail -3
