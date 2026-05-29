#!/bin/bash
# POC test: simulate the 4 operations the Imager needs
# 1. Read /etc/passwd, modify pi → artoo + /home/pi → /home/artoo
# 2. Write back modified passwd (rm old, write new)
# 3. Same for shadow + group (just passwd is enough to prove pattern)
# 4. Rename /home/pi → /home/artoo (try debugfs 'rename' command)
# 5. e2fsck -fn must be clean

set -e
F="$1"
[ -z "$F" ] && { echo "usage: $0 fixture.img"; exit 1; }

echo "=== STEP 1: list debugfs commands relevant to us ==="
debugfs -R 'help' "$F" 2>&1 | grep -iE "^( mv| rename| rm| mkdir| write| cd| ln| chroot| cat)" | head -20
echo ""

echo "=== STEP 2: read /etc/passwd, modify with sed (pi → artoo), write back ==="
debugfs -R 'cat /etc/passwd' "$F" 2>/dev/null | grep -v "^debugfs" > /tmp/passwd_orig
echo "ORIGINAL:"
cat /tmp/passwd_orig
echo ""
sed 's|^pi:x:1000:1000:,,,:/home/pi:|artoo:x:1000:1000:,,,:/home/artoo:|' /tmp/passwd_orig > /tmp/passwd_new
echo "NEW:"
cat /tmp/passwd_new
echo ""

# Mutation strategy: rm + write (recreate the file)
cat > /tmp/mut.txt <<EOF
rm /etc/passwd
write /tmp/passwd_new /etc/passwd
quit
EOF
debugfs -w -f /tmp/mut.txt "$F" 2>&1 | tail -5

echo ""
echo "=== STEP 3: verify mutation persisted ==="
debugfs -R 'cat /etc/passwd' "$F" 2>/dev/null | grep -v "^debugfs"
echo ""

echo "=== STEP 4: try rename /home/pi → /home/artoo (does debugfs have mv?) ==="
cat > /tmp/rename.txt <<EOF
rename /home/pi /home/artoo
quit
EOF
debugfs -w -f /tmp/rename.txt "$F" 2>&1 | tail -3

echo "Verify:"
debugfs -R 'ls -l /home' "$F" 2>&1 | tail -5

echo ""
echo "=== STEP 5: e2fsck after mutations ==="
e2fsck -fn "$F" 2>&1 | tail -5
