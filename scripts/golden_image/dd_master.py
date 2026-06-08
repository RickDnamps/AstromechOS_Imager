"""dd_master.py — Official Golden Image DD pipeline (Master Pi).

SSH to the master Pi (assumed already booted with the SSD attached via USB),
mount the SSD, run pi_cleanup.sh, then DD /dev/mmcblk0 to the SSD-attached
.img file. Auto-detects mmcblk0 size at runtime via blockdev --getsize64
(anti-regression: works on any SD size).

Anti-regression invariants (gravé dans le béton via marathon 2026-06-02→07):
  - EXPECTED_SIZE is None at module top → auto-detected via blockdev
    (NEVER hardcode size; breaks the moment operator swaps SD card sizes)
  - DD uses stream=False (no live PTY) — avoids paramiko readline timeout
    during the long-running dd. Progress polled via separate SSH session every 60s
  - Real dd exit code captured + explicit post-DD size verification
  - pi_cleanup.sh runs FIRST (truncate logs, vacuum journal, clear bash history)

PREREQS — see ./README.md
"""
import io, sys, time, threading
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                              write_through=True, line_buffering=True)

MASTER_IP = "192.168.2.104"
PWD = "astropass123"
LOCAL_CLEANUP = r"J:\R2-D2_Build\AstroMechOS_Imager\scripts\golden_image\pi_cleanup.sh"
REMOTE_CLEANUP = "/tmp/pi_cleanup_patched.sh"
TARGET = "/mnt/ssd/AstromechOS_Master_07-06-2026.img"
EXPECTED_SIZE = None  # auto-detected at runtime via blockdev --getsize64 /dev/mmcblk0


def run(c, cmd, label, timeout=60, stream=False):
    print(f"  -> {label}", flush=True)
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout, get_pty=stream)
    if stream:
        for line in iter(stdout.readline, ""):
            if not line:
                break
            print(f"     | {line.rstrip()}", flush=True)
        rc = stdout.channel.recv_exit_status()
    else:
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc = stdout.channel.recv_exit_status()
        if out.strip():
            for line in out.strip().splitlines()[:10]:
                print(f"     | {line}", flush=True)
        if err.strip():
            for line in err.strip().splitlines()[:5]:
                print(f"     ! {line}", flush=True)
    print(f"     [exit {rc}]", flush=True)
    return rc


print(f"=== A. SSH Master + detect SSD ===", flush=True)
m = paramiko.SSHClient()
m.set_missing_host_key_policy(paramiko.AutoAddPolicy())
m.connect(MASTER_IP, username="astromech", password=PWD, timeout=15,
          allow_agent=False, look_for_keys=False)
print("  Master connected", flush=True)

_, out, _ = m.exec_command(
    "lsblk -dno NAME,SIZE,TYPE,TRAN | awk '$3==\"disk\" && $4==\"usb\" && $2!~/^0/ {print $1}' | head -1",
    timeout=10)
ssd_dev = out.read().decode().strip()
if not ssd_dev:
    print("  !!! Cannot detect USB SSD — abort !!!", flush=True)
    m.close(); sys.exit(1)
print(f"  Detected SSD: /dev/{ssd_dev}", flush=True)
SSD_PART = f"/dev/{ssd_dev}1"

# A1. Auto-detect mmcblk0 EXACT size (anti-regression vs hardcoded)
_, out, _ = m.exec_command(
    f"echo {PWD} | sudo -S blockdev --getsize64 /dev/mmcblk0 2>&1", timeout=10)
mmc_size_str = out.read().decode().strip().splitlines()[-1]
EXPECTED_SIZE = int(mmc_size_str)
print(f"  Detected mmcblk0 size: {EXPECTED_SIZE:,} bytes ({EXPECTED_SIZE/1e9:.2f} GB)",
      flush=True)

# A2. Mount SSD (flashed Pi doesn't have fstab auto-mount)
print(f"\n=== A2. Mount SSD {SSD_PART} → /mnt/ssd ===", flush=True)
run(m, f"echo {PWD} | sudo -S mkdir -p /mnt/ssd 2>&1", "mkdir mount point")
_, out, _ = m.exec_command("mountpoint /mnt/ssd 2>&1", timeout=5)
if "is a mountpoint" not in out.read().decode():
    rc = run(m, f"echo {PWD} | sudo -S mount -t exfat {SSD_PART} /mnt/ssd 2>&1",
             f"mount {SSD_PART} as exfat")
    if rc != 0:
        print("  !!! mount failed — abort !!!", flush=True)
        m.close(); sys.exit(rc)
else:
    print("  /mnt/ssd already mounted", flush=True)
run(m, "df -h /mnt/ssd | tail -1", "SSD mount confirmed")

# B. SCP cleanup
print(f"\n=== B. SCP + patch pi_cleanup.sh ({SSD_PART}) ===", flush=True)
sftp = m.open_sftp()
sftp.put(LOCAL_CLEANUP, REMOTE_CLEANUP)
sftp.chmod(REMOTE_CLEANUP, 0o755)
sftp.close()
if ssd_dev != "sda":
    run(m, f"sed -i 's|/dev/sda1|{SSD_PART}|g' {REMOTE_CLEANUP}", "patch device")

print(f"\n=== C. pi_cleanup.sh master ===", flush=True)
rc = run(m, f"echo {PWD} | sudo -S bash {REMOTE_CLEANUP} master 2>&1",
         "pi_cleanup master", timeout=300, stream=True)
if rc != 0:
    print("  !!! pi_cleanup failed — abort !!!", flush=True)
    m.close(); sys.exit(rc)

print("\n=== D. Erase partial+old .img ===", flush=True)
run(m, "ls -la /mnt/ssd/AstromechOS_*.img 2>&1 | head -5", "Current images")
run(m, f"echo {PWD} | sudo -S rm -f /mnt/ssd/AstromechOS_Master_*.img 2>&1", "rm Master only (preserve Slave.img if present)")
run(m, "df -h /mnt/ssd", "SSD usage")

print("\n=== E. Final cleanup ===", flush=True)
run(m, f"echo {PWD} | sudo -S find /var/log -type f -name '*.log' -exec truncate -s 0 {{}} + 2>&1",
    "Re-truncate logs")
run(m, f"echo {PWD} | sudo -S journalctl --vacuum-size=1M 2>&1 | tail -3", "Vacuum")
run(m, f"echo {PWD} | sudo -S rm -rf /tmp/* /tmp/.[!.]* /var/tmp/* /var/tmp/.[!.]* 2>&1", "Clear tmp")
run(m, f"echo {PWD} | sudo -S sh -c ': > /home/astromech/.bash_history; : > /root/.bash_history' 2>&1",
    "Clear bash history")
run(m, "sync && echo synced", "Sync")
run(m, f"echo {PWD} | sudo -S sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>&1", "Drop caches")

# === F. DD — stream=False (blocking) + size check after ===
print(f"\n=== F. DD Master → SSD (blocking, ~50 min) ===", flush=True)
print(f"Target: {TARGET}", flush=True)
print(f"NOTE: no live progress (avoids paramiko PTY timeout); polled via 2nd SSH session", flush=True)
print()

# Spawn a polling thread that opens a SEPARATE SSH session every 60s and
# logs the current image size. Independent of the main dd channel.
stop_poll = threading.Event()
def poll():
    while not stop_poll.wait(60):
        try:
            p = paramiko.SSHClient()
            p.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            p.connect(MASTER_IP, username="astromech", password=PWD, timeout=10,
                      banner_timeout=15, allow_agent=False, look_for_keys=False)
            _, pout, _ = p.exec_command(f"stat -c %s {TARGET} 2>/dev/null", timeout=10)
            sz = pout.read().decode().strip()
            if sz:
                gb = int(sz) / 1e9
                pct = int(sz) * 100 / EXPECTED_SIZE
                print(f"  [poll {time.strftime('%H:%M:%S')}] {gb:.2f} GB ({pct:.1f}%)",
                      flush=True)
            p.close()
        except Exception as e:
            print(f"  [poll fail: {type(e).__name__}]", flush=True)

poll_thread = threading.Thread(target=poll, daemon=True)
poll_thread.start()

run(m, "sync", "Pre-DD sync")

# Real dd command, blocking until done. status=progress goes to stderr,
# captured by paramiko but we don't stream it.
dd_cmd = (
    f"echo {PWD} | sudo -S dd if=/dev/mmcblk0 of={TARGET} "
    f"bs=4M conv=fdatasync 2>&1"
)
t0 = time.time()
_, out, _ = m.exec_command(dd_cmd, timeout=3600)
dd_output = out.read().decode(errors="replace")
dd_rc = out.channel.recv_exit_status()
dt = time.time() - t0
stop_poll.set()

print(f"\n  -> dd finished in {dt/60:.1f} min, exit {dd_rc}", flush=True)
if dd_output.strip():
    for line in dd_output.strip().splitlines()[-5:]:
        print(f"     | {line}", flush=True)

if dd_rc != 0:
    print(f"  !!! DD FAILED (rc={dd_rc}) !!!", flush=True)
    m.close(); sys.exit(dd_rc)

run(m, "sync", "Post-DD sync")

# === G. Size verification ===
print(f"\n=== G. Size verification ===", flush=True)
_, out, _ = m.exec_command(f"stat -c %s {TARGET}", timeout=10)
actual = int(out.read().decode().strip())
print(f"  actual:   {actual:,} bytes ({actual/1e9:.2f} GB)", flush=True)
print(f"  expected: {EXPECTED_SIZE:,} bytes ({EXPECTED_SIZE/1e9:.2f} GB)", flush=True)
if actual != EXPECTED_SIZE:
    print(f"  ❌ SIZE MISMATCH (diff: {EXPECTED_SIZE - actual:,} bytes)", flush=True)
    m.close(); sys.exit(2)
print("  ✅ size matches exactly", flush=True)

run(m, f"ls -la {TARGET}", "Final listing")
run(m, "df -h /mnt/ssd", "SSD usage post-DD")

sftp = m.open_sftp()
try: sftp.remove(REMOTE_CLEANUP)
except Exception: pass
sftp.close()
m.close()

print("\n" + "=" * 72, flush=True)
print(f"✅ MASTER DD v4 DONE — image at {TARGET}", flush=True)
print(f"   Size: {actual/1e9:.2f} GB (matches mmcblk0)", flush=True)
print("=" * 72, flush=True)
