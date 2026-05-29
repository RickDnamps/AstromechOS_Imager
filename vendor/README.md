# Bundled binaries

PyInstaller picks up everything in this directory and ships it inside the
final `.exe`. The Imager resolves these binaries at runtime via
`sys._MEIPASS` (frozen) or `vendor/` (dev).

## Required files

- `debugfs.exe` — from e2fsprogs Windows port (e.g. msys2's e2fsprogs package)
- `e2fsck.exe` — same source
- `msys-2.0.dll` — required runtime if the binaries above were built with MSYS2

## Where to obtain

The recommended source is msys2's `e2fsprogs` package. On a Windows machine
with msys2 installed:

```powershell
# In a MINGW64 shell
pacman -S e2fsprogs
# Then copy these to the project's vendor/ folder:
#   C:\msys64\usr\bin\debugfs.exe
#   C:\msys64\usr\bin\e2fsck.exe
#   C:\msys64\usr\bin\msys-2.0.dll
```

These are deliberately NOT committed to git (binary blobs + transitive
license obligations). The PyInstaller build picks them up from this
directory automatically.
