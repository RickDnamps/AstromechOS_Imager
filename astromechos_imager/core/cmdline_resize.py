"""Wire the Pi-OS first-boot rootfs auto-resize into /cmdline.txt.

FAT-partition-only: the Imager appends ``init_resize.sh`` to the boot
partition's cmdline.txt so the Pi expands the rootfs to fill the SD card on
first boot; init_resize.sh then removes the arg itself. Idempotent.
"""
from __future__ import annotations

from astromechos_imager.core.errors import CmdlineInjectionFailedError
from astromechos_imager.core.platform_io import BootPartition

RESIZE_INIT_ARG = "init=/usr/lib/raspberrypi-sys-mod/init_resize.sh"


def ensure_resize_init_in_cmdline(cmdline_bytes: bytes) -> bytes:
    """Append the resize init arg to a cmdline.txt byte string if absent.

    Idempotent: returns the input byte-identical when the arg is already there.
    """
    text = cmdline_bytes.decode("ascii", errors="strict").rstrip("\n").rstrip()
    args = text.split()
    if RESIZE_INIT_ARG in args:
        return cmdline_bytes
    args.append(RESIZE_INIT_ARG)
    return (" ".join(args) + "\n").encode("ascii")


def inject_resize_arg(boot: BootPartition) -> bool:
    """Ensure /cmdline.txt on the FAT boot partition carries the resize arg.

    Returns True if the file was modified, False if it was already present.
    Raises CmdlineInjectionFailedError on read/write failure.
    """
    try:
        cmdline = boot.read_bytes("/cmdline.txt")
    except Exception as e:
        raise CmdlineInjectionFailedError(
            f"Could not read /cmdline.txt from boot partition: {e}"
        ) from e
    new_cmdline = ensure_resize_init_in_cmdline(cmdline)
    if new_cmdline == cmdline:
        return False
    try:
        boot.write_bytes("/cmdline.txt", new_cmdline)
    except Exception as e:
        raise CmdlineInjectionFailedError(
            f"Could not write /cmdline.txt to boot partition: {e}"
        ) from e
    return True
