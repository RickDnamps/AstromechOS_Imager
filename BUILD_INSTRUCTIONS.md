# AstromechOS Imager — Build & Installer

Bundles `astromechos_imager` into a Windows onedir distribution, then wraps
it in an Inno Setup installer.

## Prerequisites (one-time)

1. **Python 3.12** with the project venv active:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   .\.venv\Scripts\python.exe -m pip install pyinstaller
   ```
2. **Inno Setup 6.2+** — https://jrsoftware.org/isinfo.php
   The `iscc.exe` compiler must be in `PATH`, or invoke it by full path
   (usually `C:\Program Files (x86)\Inno Setup 6\iscc.exe`).

## Step 1 — Build the onedir bundle

From the project root:

```powershell
Remove-Item -Recurse -Force build, "dist\AstromechOS Imager" -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m PyInstaller astromechos_imager.spec --noconfirm
```

Output: `dist\AstromechOS Imager\` (~132 MB).

Spec settings to know:
- **onedir** mode — fast cold launch, no decompress-to-`%TEMP%` step.
- Custom `_filter_entries()` in the spec drops ~210 MB of unused Qt
  binaries (WebEngine, Qt3D, Charts, Multimedia, …) and unused QML
  modules. See `astromechos_imager.spec` for the drop/keep patterns.
- `console=False` + `requireAdministrator` manifest. With no console,
  Qt and Python errors are redirected to
  `%LOCALAPPDATA%\AstromechOS_Imager\startup.log` (overwritten each
  launch) — check it first if anything goes wrong.

Smoke-test:
```powershell
& "dist\AstromechOS Imager\AstromechOS Imager.exe"
Get-Content "$env:LOCALAPPDATA\AstromechOS_Imager\startup.log"
```
The window must appear within a few seconds and the log must contain
no `[Qt WARN]` / `[Qt CRIT]` lines.

## Step 2 — Compile the installer

```powershell
iscc installer\AstromechOSImager.iss
```

Or with explicit path:
```powershell
& "C:\Program Files (x86)\Inno Setup 6\iscc.exe" installer\AstromechOSImager.iss
```

Output: `dist\AstromechOS_Imager-Setup-0.2.0.exe` (~50-70 MB with
LZMA2/max compression).

## Step 3 — Release

The single `AstromechOS_Imager-Setup-x.y.z.exe` is what you ship.
Users run it, accept UAC, and get:
- App installed under `%ProgramFiles%\AstromechOS Imager\`
- Start Menu shortcut and optional desktop icon
- Proper uninstaller in Add/Remove Programs

## Updating the version

Bump in **two** places:
1. `pyproject.toml` → `version = "x.y.z"`
2. `installer\AstromechOSImager.iss` → `#define AppVersion "x.y.z"`

(Future improvement: have the `.iss` read the version from `pyproject.toml`
via a `#expr` directive.)

## Troubleshooting

| Symptom | Look here |
|---|---|
| Silent crash at launch | `%LOCALAPPDATA%\AstromechOS_Imager\startup.log` |
| `ImportError` for `PySide6.Qt*` | spec `qt_excludes` list — un-exclude it |
| QML import fails | spec `DROP_DATAS` — restore the module's `qml/Qt*/` folder |
| Missing DLL warning at runtime | spec `DROP_BINARIES` — restore the `Qt6*.dll` |
| Inno reports missing source | rebuild step 1 first |
