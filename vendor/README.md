# Bundled binaries

PyInstaller picks up the allowlisted files in this directory (see
`astromechos_imager.spec` → `_VENDOR_ALLOWLIST`) and ships them inside the
final bundle under `vendor/`. The Imager resolves them at runtime via
`sys._MEIPASS` (frozen) or `<project_root>/vendor/` (dev) — see
`astromechos_imager/core/vendored_binaries.py`.

These binaries are **gitignored** (binary blobs + transitive license
obligations), so a fresh clone must repopulate them before a build. The
steps below reproduce the exact set that ships.

## Required files

The rootfs cold surgery (UID-1000 username/password rename, in
`core/rootfs_personalizer.py`) calls these e2fsprogs tools:

- `debugfs.exe` — offline ext4 read/write (renames the UID-1000 rows)
- `e2fsck.exe`  — post-surgery filesystem integrity check

Plus their **complete Cygwin runtime DLL closure** (per `cygcheck`):

```
cygwin1.dll          cygblkid-1.dll       cygcom_err-2.dll
cyge2p-2.dll         cygext2fs-2.dll      cyggcc_s-seh-1.dll
cygiconv-2.dll       cygintl-8.dll        cygss-2.dll
cyguuid-1.dll
```

Ship ALL ten DLLs — they sit next to the `.exe`s so Windows resolves them
from the same directory at subprocess launch. Drop one and the tools fail
to load at runtime.

> Note: MSYS2 dropped the `e2fsprogs` package mid-2025, so **Cygwin** is the
> supported source. Cygwin's POSIX shim is `cygwin1.dll`, **not**
> `msys-2.0.dll`.

## Where to obtain (Cygwin)

1. Download the Cygwin installer: https://www.cygwin.com/setup-x86_64.exe
2. Install the `e2fsprogs` package. Unattended one-liner (PowerShell):

   ```powershell
   & "$env:USERPROFILE\Downloads\setup-x86_64.exe" `
       --quiet-mode --no-shortcuts --no-desktop --no-admin `
       --root "C:\cygwin64" `
       --site "https://cygwin.mirror.constant.com/" `
       --local-package-dir "$env:USERPROFILE\Downloads\cygcache" `
       --packages e2fsprogs
   ```

   The installer forks a child and returns early — wait for the
   `setup-x86_64` process to exit before copying.

3. Copy into this `vendor/` directory:
   - `C:\cygwin64\usr\sbin\debugfs.exe`
   - `C:\cygwin64\usr\sbin\e2fsck.exe`
   - the 10 `cyg*.dll` above from `C:\cygwin64\bin\`

   To recompute the DLL closure for a different e2fsprogs version:

   ```powershell
   $env:PATH = "C:\cygwin64\bin;$env:PATH"
   cygcheck C:\cygwin64\usr\sbin\debugfs.exe
   cygcheck C:\cygwin64\usr\sbin\e2fsck.exe
   ```

## Verification after population

```powershell
# Resolver finds them without raising:
.\.venv\Scripts\python.exe -c "from astromechos_imager.core.vendored_binaries import debugfs_exe, e2fsck_exe; print(debugfs_exe()); print(e2fsck_exe())"

# The .exes actually load with only the bundled DLLs (run from vendor/):
.\vendor\debugfs.exe -V
.\vendor\e2fsck.exe  -V
```

All should succeed (print version / absolute paths). When they're absent,
the runtime raises a clear `RuntimeError`, the UI shows a
"cold surgery unavailable" warning, and the flash still completes — it just
leaves the card's UID-1000 account at the golden image's default.
