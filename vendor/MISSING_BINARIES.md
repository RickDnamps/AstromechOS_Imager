# Vendor binaries — MANUAL ACTION REQUIRED before shipping

The PyInstaller build at `dist/AstromechOS Imager.exe` is **structurally complete**
but the three vendored binaries below are NOT yet included. The runtime
(`astromechos_imager/core/vendored_binaries.py`) raises a clear `RuntimeError`
when any feature that needs them is invoked.

## Required files

Drop these in this `vendor/` directory, then rerun `pyinstaller astromechos_imager.spec`:

- `debugfs.exe`   — e2fsprogs Windows port (rootfs cold-mod)
- `e2fsck.exe`    — e2fsprogs Windows port (rootfs sanity check)
- `msys-2.0.dll`  — MSYS2 / Cygwin POSIX shim (runtime DLL for both .exes above)

## Where to obtain

### Option A — Cygwin (recommended, most reliable)

1. Install Cygwin from https://www.cygwin.com/install.html (user-level, no admin needed).
2. In the package selector, mark `e2fsprogs` for install.
3. After install, copy these from `C:\cygwin64\bin\`:
   - `debugfs.exe`
   - `e2fsck.exe`
   - `cygwin1.dll`  (rename to `msys-2.0.dll`? No — keep as `cygwin1.dll` and
     update `vendored_binaries.py` accordingly. OR see Option B.)

Note: Cygwin's runtime DLL is `cygwin1.dll`, not `msys-2.0.dll`. If you go this
route, update `astromechos_imager/core/vendored_binaries.py` to look for
`cygwin1.dll` instead of `msys-2.0.dll`.

### Option B — MSYS2

MSYS2's official repos **no longer ship e2fsprogs** as of mid-2025 (verified
via packages.msys2.org API). This route is currently NOT viable.

### Option C — Standalone build

Building e2fsprogs from source against the MSYS2 toolchain is feasible but
out of scope for this README.

## Verification after population

```powershell
.\.venv\Scripts\python.exe -c "from astromechos_imager.core.vendored_binaries import debugfs_exe, e2fsck_exe; print(debugfs_exe()); print(e2fsck_exe())"
```

Both calls should print absolute paths under `vendor/` without raising.
