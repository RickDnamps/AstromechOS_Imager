# Vendor binaries — populate before building

The rootfs cold surgery (UID-1000 username/password rename) needs the
e2fsprogs tools `debugfs.exe` + `e2fsck.exe` and their Cygwin runtime DLL
closure. These are **gitignored**, so a fresh clone must repopulate them.

👉 **See `README.md` in this directory for the exact, reproducible steps**
(Cygwin install one-liner, the full list of 10 `cyg*.dll`, and the
verification commands).

When they are absent:
- the runtime resolver (`core/vendored_binaries.py`) raises a clear
  `RuntimeError`,
- the UI surfaces a "cold surgery unavailable" warning on the WRITE
  confirmation dialog,
- the flash still completes — the card just keeps the golden image's
  default UID-1000 account (no username/password rename). The mandatory
  rootfs auto-resize is unaffected (it is decoupled and FAT-only).

> Historical note: MSYS2 dropped its `e2fsprogs` package mid-2025. The old
> instructions referencing `msys-2.0.dll` / `msys-*.dll` are obsolete —
> Cygwin (`cygwin1.dll` + `cyg*.dll`) is the supported source.
