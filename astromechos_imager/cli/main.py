# astromechos_imager/cli/main.py
"""Headless CLI frontend. Per design spec §3.1, §5.7."""
from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="astromechos-imager",
        description="Two-card SD imager for the AstromechOS R2-D2 build.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    flash = sub.add_parser("flash", help="Flash one or two SD cards.")
    flash.add_argument("--master-image", type=str, default=None,
                       help="Path to master .img/.img.xz/.img.gz/.zip")
    flash.add_argument("--master-drive", type=int, default=None,
                       help="Physical drive number (e.g. 2 for \\\\.\\PHYSICALDRIVE2)")
    flash.add_argument("--slave-image", type=str, default=None)
    flash.add_argument("--slave-drive", type=int, default=None)
    flash.add_argument("--keys-file", type=str, required=True,
                       help="Path to a file containing OpenSSH pubkey(s), one per line")
    flash.add_argument("--no-verify", action="store_true",
                       help="Skip read-back SHA256 verification (discouraged)")
    # Lockstep with the GUI: the wizard hard-locks the install user to
    # DEFAULT_INSTALL_USER ("astromech"), so the CLI defaults to the same
    # name to keep one account contract across both frontends.
    from astromechos_imager.ui.flash_view_model import (
        DEFAULT_INSTALL_PASSWORD,
        DEFAULT_INSTALL_USER,
    )
    flash.add_argument("--install-user", type=str,
                       default=DEFAULT_INSTALL_USER)
    flash.add_argument("--install-password", type=str,
                       default=DEFAULT_INSTALL_PASSWORD,
                       help="Password for the UID-1000 Linux account "
                            "(default: same fallback as the GUI wizard).")
    flash.add_argument("--repo-url", type=str, default=None)
    flash.add_argument("--repo-branch", type=str, default="main")
    flash.add_argument("--hostname-master", type=str, default="astromech-master")
    flash.add_argument("--hostname-slave", type=str, default="astromech-slave")
    # wlan0 bootstrap PSK — optional; defaults to ``astropass`` (9 chars,
    # WPA2-PSK valid). Mirrors the GUI Step 4 non-blocking fallback so the
    # CLI and the wizard write the same /boot/astromech_init.cfg.
    flash.add_argument("--hotspot-psk", type=str, default="astropass",
        help="WPA2-PSK (8-63 ASCII chars) for the wlan0 Master↔Slave "
             "bootstrap AP — SSID is auto-generated per burn. "
             "Default: 'astropass'.")
    flash.add_argument("--debug", action="store_true")
    return p


def is_admin() -> bool:
    if sys.platform != "win32":
        return True  # CLI on non-Windows is fine for tests; admin check is Windows-only
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    """Re-launch the CLI with UAC elevation.

    Arguments must go through ``subprocess.list2cmdline`` so paths
    containing spaces, quotes, or backslashes survive the trip through
    Windows' ``CommandLineToArgvW``. A naive ``" ".join(sys.argv)``
    fragments such paths and is an argv-injection vector if any positional
    argument is operator-controlled.
    """
    if sys.platform != "win32":
        return
    import subprocess  # noqa: PLC0415 — only needed on Windows
    # Skip argv[0] — ShellExecuteW takes the executable as a separate
    # parameter; argv[1:] are the actual command-line arguments.
    quoted_args = subprocess.list2cmdline(sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, quoted_args, None, 1,
    )
    sys.exit(0)


def _build_platform_io():
    """Indirected so tests inject fakes."""
    if sys.platform == "win32":
        from astromechos_imager.platform.windows import WindowsPlatformIO
        return WindowsPlatformIO()
    raise RuntimeError("Imager runs on Windows only — CLI invoked from non-Windows host")


def _cmd_flash(args: argparse.Namespace) -> int:
    from astromechos_imager import __version__
    from astromechos_imager.core.keygen import (
        generate_ed25519,
        generate_hotspot_bootstrap,
        generate_linux_account,
    )
    from astromechos_imager.core.models import FirstbootConfig, Role, _utc_iso_now
    from astromechos_imager.core.orchestrator import FlashJob

    plat = _build_platform_io()
    drives = {d.physical_drive_id: d for d in plat.enumerate_removable_drives()}
    keys = [k.strip() for k in Path(args.keys_file).read_text().splitlines() if k.strip()]
    cfg = FirstbootConfig(
        authorized_keys=keys,
        install_user=args.install_user,
        repo_url=args.repo_url,
        repo_branch=args.repo_branch,
        hostname_master=args.hostname_master,
        hostname_slave=args.hostname_slave,
        hotspot_bootstrap=generate_hotspot_bootstrap(args.hotspot_psk),
        imager_version=__version__,
        flashed_at_iso=_utc_iso_now(),
    )
    pair = generate_ed25519()
    # Lockstep with the GUI: build linux_account so the CLI provisions the
    # UID-1000 account on the flashed Trixie image; without it the flash
    # would write EMPTY_USER_DATA and skip account provisioning.
    linux_account = generate_linux_account(
        args.install_user, args.install_password)

    # Sequential-only, in lockstep with the GUI's Deployment Assistant: ONE
    # card per invocation. There is no parallel pair mode — each card is
    # flashed individually so it always gets linux_account provisioning.
    if args.master_image and args.slave_image:
        print("error: flash ONE card per invocation (master first, then "
              "slave) — the parallel pair mode was removed.", file=sys.stderr)
        return 2
    if args.master_image:
        role, image, target = Role.MASTER, args.master_image, drives[args.master_drive]
    elif args.slave_image:
        role, image, target = Role.SLAVE, args.slave_image, drives[args.slave_drive]
    else:
        print("error: provide --master-image/--master-drive or "
              "--slave-image/--slave-drive.", file=sys.stderr)
        return 2
    single = FlashJob(
        platform_io=plat,
        image_path=Path(image),
        target=target,
        role=role,
        firstboot_config=cfg,
        master_pair=pair,
        linux_account=linux_account,
        skip_verify=args.no_verify,
    )
    return 0 if single.run().ok else 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not is_admin():
        relaunch_as_admin()
        return 0
    if args.command == "flash":
        return _cmd_flash(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
