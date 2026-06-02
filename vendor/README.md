# Bundled binaries

The PyInstaller build ships the allowlisted files in this directory under
`vendor/` (see `astromechos_imager.spec`). The Imager resolves them at runtime
via `sys._MEIPASS` (frozen) or `<project_root>/vendor/` (dev) — see
`astromechos_imager/core/vendored_binaries.py`.

## Files

- `astro_flash.dll` — native "shell-quiet" helper (suppresses the Windows
  Explorer "Format?" dialog during raw device I/O). Optional: without it the
  app degrades to a pure-Python no-op. Loaded by
  `astromechos_imager/platform/native_shell_quiet.py`.

These binaries are gitignored (binary blobs); a fresh clone runs fine without
them (the DLL is optional).
