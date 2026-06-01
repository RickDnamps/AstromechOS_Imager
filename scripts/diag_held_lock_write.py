"""Proof for the ACCESS_DENIED fix: does HOLDING FSCTL_LOCK_VOLUME for the
whole flash authorise a raw write INSIDE a Windows-recognised partition,
WITHOUT IOCTL_DISK_DELETE_DRIVE_LAYOUT?

The user hit OSError(5) ACCESS_DENIED at the FAT32 start offset once
DELETE_DRIVE_LAYOUT was removed, because the old lock_and_dismount released
the lock immediately and Windows re-mounted/re-protected the partition.
The new lock_and_dismount keeps the lock held. This probe reproduces the
exact failing condition (a recognised FAT32 at 1 MB) and writes the FAT32
start sector back to itself (NON-DESTRUCTIVE — reads then writes the same
1 MB), reporting whether the held lock authorises the write.
"""
import ctypes
import io
import sys
from ctypes import wintypes
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.platform import windows as W
from astromechos_imager.platform._win32 import (
    GENERIC_READ, GENERIC_WRITE, FILE_SHARE_READ, FILE_SHARE_WRITE,
    OPEN_EXISTING, FILE_FLAG_NO_BUFFERING, FILE_FLAG_WRITE_THROUGH,
    FILE_FLAG_SEQUENTIAL_SCAN, INVALID_HANDLE_VALUE, kernel32,
)

ALIGN = 4096
OFF = 1 * 1024 * 1024   # FAT32 partition start (startLBA=2048) — the exact
                        # in-partition offset that returned ACCESS_DENIED.


def main() -> int:
    d = list(W.enumerate_removable_drives())[0]
    phys = d.physical_drive_id
    print(f"phys_id={phys} letters={d.drive_letters}")

    print("lock_and_dismount(letters, phys) — HOLDING the lock...")
    held = W.lock_and_dismount(d.drive_letters, phys)
    print(f"  held {len(held)} locked volume handle(s)")

    path = f"\\\\.\\PHYSICALDRIVE{phys}"
    flags = FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH | FILE_FLAG_SEQUENTIAL_SCAN
    h = kernel32().CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                               FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                               OPEN_EXISTING, flags, None)
    if h == INVALID_HANDLE_VALUE:
        print("open failed", ctypes.get_last_error())
        for x in held:
            W.close_handle(x)
        return 2

    backing = (ctypes.c_char * ((1 << 20) + ALIGN))()
    aligned = (ctypes.addressof(backing) + ALIGN - 1) & ~(ALIGN - 1)
    buf = (ctypes.c_char * (1 << 20)).from_address(aligned)

    p = ctypes.c_longlong(0)
    kernel32().SetFilePointerEx(h, ctypes.c_longlong(OFF), ctypes.byref(p), 0)
    got = wintypes.DWORD(0)
    if not kernel32().ReadFile(h, buf, 1 << 20, ctypes.byref(got), None):
        print("read @1MB failed", ctypes.get_last_error())
        kernel32().CloseHandle(h)
        for x in held:
            W.close_handle(x)
        return 3
    print(f"read @1MB ok ({got.value}B)")

    kernel32().SetFilePointerEx(h, ctypes.c_longlong(OFF), ctypes.byref(p), 0)
    wr = wintypes.DWORD(0)
    ok = kernel32().WriteFile(h, buf, 1 << 20, ctypes.byref(wr), None)
    err = 0 if ok else ctypes.get_last_error()
    kernel32().CloseHandle(h)
    for x in held:        # release the held locks → Windows may remount
        W.close_handle(x)

    print("\n== VERDICT ==")
    if ok:
        print("  🟢 write @1MB SUCCEEDED inside the recognised FAT32 while "
              "holding the volume lock — NO DELETE_DRIVE_LAYOUT needed. "
              "The ACCESS_DENIED is fixed.")
        return 0
    print(f"  🔴 write @1MB FAILED err={err} "
          f"({'ACCESS_DENIED' if err == 5 else 'other'}) — holding the lock "
          "did NOT authorise the write; need another approach.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
