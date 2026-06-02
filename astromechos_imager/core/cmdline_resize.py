"""Wire the Pi-OS first-boot rootfs auto-resize into /cmdline.txt.

FAT-partition-only: the Imager appends ``init_resize.sh`` to the boot
partition's cmdline.txt so the Pi expands the rootfs to fill the SD card on
first boot; init_resize.sh then removes the arg itself. Idempotent.
"""
from __future__ import annotations

import logging

from astromechos_imager.core.errors import CmdlineInjectionFailedError
from astromechos_imager.core.platform_io import BootPartition

_log = logging.getLogger(__name__)

# Pi OS first-boot resize: the kernel execs this as PID 1, it grows the rootfs
# to fill the card, then strips this exact token from cmdline.txt and reboots.
# Path verified on the golden image rootfs (the script lives at
# /usr/lib/raspi-config/init_resize.sh; /usr/lib/raspberrypi-sys-mod does not
# even exist there) — a wrong path is exec'd as PID 1 and panics the boot.
RESIZE_INIT_ARG = "init=/usr/lib/raspi-config/init_resize.sh"


def ensure_resize_init_in_cmdline(cmdline_bytes: bytes) -> bytes:
    """Add the resize init arg to a cmdline.txt byte string iff no init= is set.

    The kernel execs ``init=`` as PID 1, so a valid cmdline carries AT MOST one.
    This function is therefore conservative about not creating contradictory
    directives:

    * No ``init=`` at all (the normal Golden-image case — pishrink runs with
      ``-s`` so no autoexpand hook is baked in) → our resize arg is appended.
    * Our own resize arg already present → returned byte-identical (idempotent).
    * A *foreign* ``init=`` already present (a card previously flashed by an
      older tool, or a Golden built without ``-s``) → returned byte-identical
      and a warning is logged. We defer to the existing directive rather than
      append a second, conflicting one — re-flashing always overwrites the
      whole cmdline from the bare Golden first, so this branch only guards
      against pathological inputs.
    """
    text = cmdline_bytes.decode("ascii", errors="strict").rstrip("\n").rstrip()
    args = text.split()
    existing = next((a for a in args if a.startswith("init=")), None)
    if existing is not None:
        if existing != RESIZE_INIT_ARG:
            _log.warning(
                "cmdline.txt already carries a foreign init= (%s); deferring to "
                "it and NOT adding the resize arg, to avoid two PID-1 directives",
                existing,
            )
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
