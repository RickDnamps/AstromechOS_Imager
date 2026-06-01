"""Dump the current MBR partition table + FAT32 boot sector of the SD,
to see whether the on-disk layout is the correct Pi-OS layout or garbage.
"""
import ctypes
import io
import struct
import sys
from ctypes import wintypes
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.platform._win32 import (
    GENERIC_READ, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING,
    INVALID_HANDLE_VALUE, kernel32,
)
from astromechos_imager.platform import windows as W


def main() -> int:
    phys = list(W.enumerate_removable_drives())[0].physical_drive_id
    path = f"\\\\.\\PHYSICALDRIVE{phys}"
    h = kernel32().CreateFileW(path, GENERIC_READ,
                               FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                               OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE_VALUE:
        print("open err", ctypes.get_last_error()); return 2

    def rd(off, n):
        p = ctypes.c_longlong(0)
        kernel32().SetFilePointerEx(h, ctypes.c_longlong(off), ctypes.byref(p), 0)
        b = ctypes.create_string_buffer(n)
        g = wintypes.DWORD(0)
        kernel32().ReadFile(h, b, n, ctypes.byref(g), None)
        return bytes(b.raw[: g.value])

    mbr = rd(0, 512)
    print(f"phys_id={phys}")
    print(f"MBR signature : {mbr[510:512].hex()} (expect 55aa)")
    print(f"MBR first 16  : {mbr[:16].hex()}")
    print("partition table:")
    for i in range(4):
        e = mbr[446 + i*16: 446 + i*16 + 16]
        if any(e):
            ptype = e[4]
            lba = struct.unpack("<I", e[8:12])[0]
            sz = struct.unpack("<I", e[12:16])[0]
            print(f"  part{i+1}: type=0x{ptype:02x} startLBA={lba} "
                  f"({lba*512/1024**2:.1f}MB) sizeLBA={sz} ({sz*512/1024**2:.1f}MB)")
        else:
            print(f"  part{i+1}: (empty)")
    fat = rd(8 * 1024 * 1024, 512)
    print(f"FAT@8MB sig   : {fat[510:512].hex()}  OEM: {fat[3:11]!r}")
    kernel32().CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
