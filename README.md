# AstromechOS Imager

Windows desktop tool that flashes two SD cards (one Master, one Slave) for
the AstromechOS R2-D2 build in a single guided session. Pre-configures
each card with role-specific firstboot bundle (hostname, SSH access,
Master→Slave keypair, hotspot bootstrap creds) and personalizes the
rootfs offline (rename UID-1000 user, set Linux password, inject
init_resize.sh for first-boot rootfs expansion).

Companion: https://github.com/RickDnamps/AstromechOS

## Requirements

- Windows 10/11 (x86_64)
- Python 3.12 (for dev only — the bundled `.exe` ships its own runtime)
- Admin rights at runtime (raw disk write + offline ext4 modification)

## Dev install

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
```

Populate `vendor/` with `debugfs.exe`, `e2fsck.exe`, `msys-2.0.dll`
(see `vendor/README.md`).

## CLI usage

```powershell
astromechos-imager flash `
    --master-image C:\images\master.img.xz `
    --master-drive 2 `
    --slave-image C:\images\slave.img.xz `
    --slave-drive 3 `
    --keys-file C:\Users\you\.ssh\id_ed25519.pub
```

## Build the .exe

```powershell
pyinstaller astromechos_imager.spec
```

Output: `dist\AstromechOS Imager.exe` (admin-manifested, single file).

## License

GPL-3.0-or-later (compatible with AstromechOS).
