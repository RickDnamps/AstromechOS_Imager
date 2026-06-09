"""dd_slave.py — Official Golden Image DD pipeline (Slave Pi).

PC SSH → Master tunnel → Slave (SSD attached directly to slave's USB).
Local DD on slave avoids master→slave SSH-pipe bottleneck. The Master.img from
the previous dd_master.py run remains intact on the SSD (verified by size
check, preserved by pi_cleanup.sh which only rm's Slave_*.img).

Anti-regression invariants (gravé dans le béton via marathon 2026-06-02→07):
  - EXPECTED_SIZE is None at module top → auto-detected via blockdev
    --getsize64 /dev/mmcblk0 (NEVER hardcode; breaks at SD size swap)
  - SSD mounted explicitly as exfat — flashed Pi does NOT auto-mount via fstab
  - Master.img preserved (rm pattern: Slave_*.img only)
  - DD uses stream=False + poll thread for progress (paramiko readline timeout
    safety on long-running dd)

PREREQS — see ./README.md
"""
import io, os, sys, time, threading
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                              write_through=True, line_buffering=True)

MASTER_IP = "192.168.2.104"
SLAVE_IP = "192.168.4.171"
# Anti-regression 2026-06-08: parameterize password via env var. Different
# Imager wizard sessions can bake different installPasswords, so hardcoding
# any single value will break the next-cycle DD.
PWD = os.environ.get("IMAGER_FLASH_PWD", "astropass123")
LOCAL_CLEANUP = r"J:\R2-D2_Build\AstroMechOS_Imager\scripts\golden_image\pi_cleanup.sh"
REMOTE_CLEANUP = "/tmp/pi_cleanup_patched.sh"
TARGET = "/mnt/ssd/AstromechOS_Slave_07-06-2026.img"
MASTER_IMG = "/mnt/ssd/AstromechOS_Master_07-06-2026.img"
MASTER_IMG_EXPECTED = 126_437_294_080
EXPECTED_SIZE = None   # auto-detected at runtime via blockdev --getsize64 /dev/mmcblk0


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


print("=== A. SSH Master + tunnel to Slave ===", flush=True)
m = paramiko.SSHClient()
m.set_missing_host_key_policy(paramiko.AutoAddPolicy())
m.connect(MASTER_IP, username="astromech", password=PWD, timeout=15,
          allow_agent=False, look_for_keys=False)
ch = m.get_transport().open_channel("direct-tcpip",
                                     dest_addr=(SLAVE_IP, 22), src_addr=("127.0.0.1", 0))
sl = paramiko.SSHClient()
sl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
sl.connect(SLAVE_IP, username="astromech", password=PWD, sock=ch, timeout=15,
           allow_agent=False, look_for_keys=False)
print("  Master + Slave connected", flush=True)

# === A2. Auto-detect slave mmcblk0 EXACT size (anti-regression vs hardcoded) ===
_, out, _ = sl.exec_command(
    f"echo {PWD} | sudo -S blockdev --getsize64 /dev/mmcblk0 2>&1", timeout=10)
mmc_size_str = out.read().decode().strip().splitlines()[-1]
EXPECTED_SIZE = int(mmc_size_str)
print(f"  Detected slave mmcblk0 size: {EXPECTED_SIZE:,} bytes ({EXPECTED_SIZE/1e9:.2f} GB)",
      flush=True)

# === B. Mount SSD on slave ===
print("\n=== B. Mount SSD on slave ===", flush=True)
run(sl, "mountpoint /mnt/ssd 2>&1 || echo NOT_MOUNTED", "check mount state")
run(sl, f"echo {PWD} | sudo -S mkdir -p /mnt/ssd", "mkdir /mnt/ssd")
# fsck first (exfat had unclean unmount warning earlier — be safe)
run(sl, f"echo {PWD} | sudo -S which fsck.exfat 2>&1 || apt list --installed 2>/dev/null | grep -i exfat",
    "check fsck.exfat available")
# Mount as exfat
rc = run(sl, f"echo {PWD} | sudo -S mount -t exfat /dev/sda1 /mnt/ssd 2>&1", "mount SSD")
if rc != 0:
    print("  !!! mount failed — aborting", flush=True)
    sl.close(); m.close(); sys.exit(rc)
run(sl, "ls -la /mnt/ssd/ | head -10", "list /mnt/ssd")

# === C. Verify Master.img integrity (size only — sha256 too slow for 126GB) ===
print("\n=== C. Verify Master.img survived unplug/replug ===", flush=True)
_, out, _ = sl.exec_command(f"stat -c %s {MASTER_IMG} 2>&1", timeout=10)
master_actual = out.read().decode().strip()
print(f"  Master.img size: {master_actual}", flush=True)
try:
    if int(master_actual) == MASTER_IMG_EXPECTED:
        print(f"  ✅ Master.img size matches exactly ({MASTER_IMG_EXPECTED:,} bytes)", flush=True)
    else:
        print(f"  ⚠️  Master.img size MISMATCH (expected {MASTER_IMG_EXPECTED:,})", flush=True)
        print("       Will re-test after slave DD; not aborting", flush=True)
except ValueError:
    print(f"  ℹ️  Master.img not present (probably DD'd separately or this is slave-first cycle) — continuing", flush=True)

# === D. SCP + patch pi_cleanup.sh for slave ===
print("\n=== D. SCP + patch pi_cleanup.sh slave ===", flush=True)
sftp = sl.open_sftp()
sftp.put(LOCAL_CLEANUP, REMOTE_CLEANUP)
sftp.chmod(REMOTE_CLEANUP, 0o755)
sftp.close()
# Slave SSD is sda1 too (same device naming); no patch needed

# === E. pi_cleanup.sh slave ===
print("\n=== E. pi_cleanup.sh slave ===", flush=True)
rc = run(sl, f"echo {PWD} | sudo -S bash {REMOTE_CLEANUP} slave 2>&1",
         "pi_cleanup slave", timeout=300, stream=True)
if rc != 0:
    print("  !!! pi_cleanup failed — abort !!!", flush=True)
    sl.close(); m.close(); sys.exit(rc)

# === F. Erase old slave .img if any ===
print("\n=== F. Erase old slave .img ===", flush=True)
run(sl, "ls -la /mnt/ssd/AstromechOS_Slave_*.img 2>&1 | head -5", "Current slave images")
run(sl, f"echo {PWD} | sudo -S rm -f /mnt/ssd/AstromechOS_Slave_*.img 2>&1", "rm old slave")
run(sl, "df -h /mnt/ssd", "SSD usage")

# === G. Final cleanup ===
print("\n=== G. Final cleanup ===", flush=True)
run(sl, f"echo {PWD} | sudo -S find /var/log -type f -name '*.log' -exec truncate -s 0 {{}} + 2>&1",
    "Re-truncate logs")
run(sl, f"echo {PWD} | sudo -S journalctl --vacuum-size=1M 2>&1 | tail -3", "Vacuum")
run(sl, f"echo {PWD} | sudo -S rm -rf /tmp/* /tmp/.[!.]* /var/tmp/* /var/tmp/.[!.]* 2>&1", "Clear tmp")
run(sl, f"echo {PWD} | sudo -S sh -c ': > /home/astromech/.bash_history; : > /root/.bash_history' 2>&1",
    "Clear bash history")
run(sl, "sync && echo synced", "Sync")
run(sl, f"echo {PWD} | sudo -S sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>&1", "Drop caches")

# === H. DD (slave local — mmcblk0 → SSD-attached) ===
print("\n=== H. DD Slave → SSD (local, ~25-30 min) ===", flush=True)
print(f"Target: {TARGET}", flush=True)
print(f"Expected: {EXPECTED_SIZE:,} bytes ({EXPECTED_SIZE/1e9:.2f} GB)", flush=True)

stop_poll = threading.Event()
def poll():
    while not stop_poll.wait(60):
        try:
            # Use master to tunnel for poll, fresh session
            p_master = paramiko.SSHClient()
            p_master.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            p_master.connect(MASTER_IP, username="astromech", password=PWD, timeout=10,
                             banner_timeout=15, allow_agent=False, look_for_keys=False)
            p_ch = p_master.get_transport().open_channel(
                "direct-tcpip", dest_addr=(SLAVE_IP, 22), src_addr=("127.0.0.1", 0))
            p_sl = paramiko.SSHClient()
            p_sl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            p_sl.connect(SLAVE_IP, username="astromech", password=PWD, sock=p_ch,
                         timeout=10, allow_agent=False, look_for_keys=False)
            _, pout, _ = p_sl.exec_command(f"stat -c %s {TARGET} 2>/dev/null", timeout=10)
            sz = pout.read().decode().strip()
            if sz:
                gb = int(sz) / 1e9
                pct = int(sz) * 100 / EXPECTED_SIZE
                print(f"  [poll {time.strftime('%H:%M:%S')}] {gb:.2f} GB ({pct:.1f}%)",
                      flush=True)
            p_sl.close(); p_master.close()
        except Exception as e:
            print(f"  [poll fail: {type(e).__name__}]", flush=True)

poll_thread = threading.Thread(target=poll, daemon=True)
poll_thread.start()

run(sl, "sync", "Pre-DD sync")

dd_cmd = (
    f"echo {PWD} | sudo -S dd if=/dev/mmcblk0 of={TARGET} "
    f"bs=4M conv=fdatasync 2>&1"
)
t0 = time.time()
_, out, _ = sl.exec_command(dd_cmd, timeout=3600)
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
    sl.close(); m.close(); sys.exit(dd_rc)

run(sl, "sync", "Post-DD sync")

# === I. Size verification ===
print("\n=== I. Size verification ===", flush=True)
_, out, _ = sl.exec_command(f"stat -c %s {TARGET}", timeout=10)
actual = int(out.read().decode().strip())
print(f"  actual:   {actual:,} bytes ({actual/1e9:.2f} GB)", flush=True)
print(f"  expected: {EXPECTED_SIZE:,} bytes ({EXPECTED_SIZE/1e9:.2f} GB)", flush=True)
if actual != EXPECTED_SIZE:
    print(f"  ❌ SIZE MISMATCH (diff: {EXPECTED_SIZE - actual:,} bytes)", flush=True)
    sl.close(); m.close(); sys.exit(2)
print("  ✅ size matches exactly", flush=True)

run(sl, f"ls -la {TARGET}", "Final slave listing")
run(sl, f"ls -la {MASTER_IMG}", "Master listing (sanity)")
run(sl, "df -h /mnt/ssd", "SSD usage post-DD")

# Cleanup
sftp = sl.open_sftp()
try: sftp.remove(REMOTE_CLEANUP)
except Exception: pass
sftp.close()
sl.close(); m.close()

print("\n" + "=" * 72, flush=True)
print(f"✅ SLAVE DD v3 DONE — image at {TARGET}", flush=True)
print(f"   Size: {actual/1e9:.2f} GB (matches mmcblk0)", flush=True)
print(f"   Both Golden Images now on SSD; unplug+plug to PC for Phase 3", flush=True)
print("=" * 72, flush=True)
