"""RootfsPersonalizer — orchestrates the 4-step cold modification of a rootfs.

Per design spec §2.2.1:
  1. Rename the UID-1000 entry in /etc/passwd (name + home).
  2. Rename + replace password hash in /etc/shadow.
  3. Rename primary group + update group memberships in /etc/group.
  4. Rename /home/<old> → /home/<new> in the filesystem.

Then self-validates by re-reading /etc/passwd and runs e2fsck.

Phase 5.5.3 amendment: also injects the Pi OS first-boot rootfs auto-resize
trigger into /cmdline.txt on the FAT32 boot partition (when a boot partition
is provided).
"""
from __future__ import annotations

from astromechos_imager.core.errors import (
    CmdlineInjectionFailedError,
    RootfsFsckError,
    RootfsSelfValidationFailedError,
    UidNotFoundError,
)
from astromechos_imager.core.models import LinuxAccount
from astromechos_imager.core.passwd_files import (
    parse_group,
    parse_passwd,
    parse_shadow,
    rename_user_in_group,
    rename_user_in_passwd,
    rename_user_in_shadow,
    serialize_group,
    serialize_passwd,
    serialize_shadow,
)
from astromechos_imager.core.platform_io import BootPartition, RootfsPartition

#: Kernel argument that triggers Pi OS first-boot rootfs auto-resize.
#: Pi OS's init_resize.sh expands the rootfs partition to fill the entire
#: SD card on first boot, then removes itself from /cmdline.txt so that
#: re-imaging produces the same starting condition.
RESIZE_INIT_ARG = "init=/usr/lib/raspberrypi-sys-mod/init_resize.sh"


def ensure_resize_init_in_cmdline(cmdline_bytes: bytes) -> bytes:
    """Ensure the Pi OS first-boot rootfs auto-resize is wired in /cmdline.txt.

    The file is a single line of space-separated kernel args. We append the
    init=... arg if absent. Idempotent: returns the input unchanged if the
    arg is already present.

    Parameters
    ----------
    cmdline_bytes:
        Raw bytes of /cmdline.txt on the FAT32 boot partition.

    Returns
    -------
    bytes
        Updated content (with trailing newline). If the arg was already
        present, returns the *exact same object* as input (byte-identical).
    """
    text = cmdline_bytes.decode("ascii", errors="strict").rstrip("\n").rstrip()
    args = text.split()
    if RESIZE_INIT_ARG in args:
        return cmdline_bytes  # idempotent — return verbatim
    args.append(RESIZE_INIT_ARG)
    return (" ".join(args) + "\n").encode("ascii")


class RootfsPersonalizer:
    """Orchestrate the 4-step cold rename of the UID-1000 Linux user.

    Also injects the Pi OS first-boot rootfs auto-resize trigger into
    /cmdline.txt on the FAT32 boot partition when a boot partition is provided.

    Parameters
    ----------
    account:
        The target account specification (username + crypt_sha512 hash).
    fs:
        A ``RootfsPartition`` backend providing read/write/rename/fsck on the
        ext4 rootfs partition.
    boot:
        Optional ``BootPartition`` backend. When provided, /cmdline.txt is
        updated to include the AstromechOS first-boot resize trigger arg.
        When ``None``, the cmdline step is skipped (backward-compatible).
    """

    def __init__(
        self,
        account: LinuxAccount,
        fs: RootfsPartition,
        boot: BootPartition | None = None,
    ) -> None:
        self.account = account
        self.fs = fs
        self.boot = boot

    def apply(self) -> None:
        """Perform all modification steps, then self-validate and fsck.

        Steps:
          1. /etc/passwd rename (UID-1000)
          2. /etc/shadow rename + hash replacement
          3. /etc/group rename + membership update
          4. /home/<old> → /home/<new> rename
          5. Self-validate by re-reading /etc/passwd
          6. e2fsck integrity check
          7. (if boot provided) inject resize init arg into /cmdline.txt

        Idempotent: if UID-1000 already has ``self.account.username``, skips
        the rename steps and only runs fsck (and the cmdline step if needed).

        Raises
        ------
        UidNotFoundError
            If no UID-1000 row exists in /etc/passwd.
        RootfsSelfValidationFailedError
            If the post-write re-read shows unexpected UID-1000 state.
        RootfsFsckError
            If e2fsck reports errors.
        CmdlineInjectionFailedError
            If reading or writing /cmdline.txt on the boot partition fails.
        """
        # ── Step 1: /etc/passwd ───────────────────────────────────────────
        rows = parse_passwd(self.fs.read_bytes("/etc/passwd"))
        uid_row = next((r for r in rows if r.uid == 1000), None)
        if uid_row is None:
            raise UidNotFoundError("No UID-1000 row found in /etc/passwd")

        old_user = uid_row.name

        if old_user == self.account.username:
            # Already at target — idempotent short-circuit; still run fsck.
            if not self.fs.fsck_clean():
                raise RootfsFsckError("e2fsck reports errors (idempotent check)")
            self._inject_cmdline()
            return

        rows = rename_user_in_passwd(rows, old_user, self.account.username)
        self.fs.write_bytes("/etc/passwd", serialize_passwd(rows))

        # ── Step 2: /etc/shadow ───────────────────────────────────────────
        shadow_rows = parse_shadow(self.fs.read_bytes("/etc/shadow"))
        shadow_rows = rename_user_in_shadow(
            shadow_rows, old_user, self.account.username, self.account.crypt_sha512
        )
        self.fs.write_bytes("/etc/shadow", serialize_shadow(shadow_rows))

        # ── Step 3: /etc/group ────────────────────────────────────────────
        group_rows = parse_group(self.fs.read_bytes("/etc/group"))
        group_rows = rename_user_in_group(group_rows, old_user, self.account.username)
        self.fs.write_bytes("/etc/group", serialize_group(group_rows))

        # ── Step 4: rename /home/<old> → /home/<new> ─────────────────────
        self.fs.rename(f"/home/{old_user}", f"/home/{self.account.username}")

        # ── Step 5: self-validate ─────────────────────────────────────────
        rows2 = parse_passwd(self.fs.read_bytes("/etc/passwd"))
        new_row = next((r for r in rows2 if r.uid == 1000), None)
        expected_home = f"/home/{self.account.username}"
        if (
            new_row is None
            or new_row.name != self.account.username
            or new_row.home != expected_home
        ):
            raise RootfsSelfValidationFailedError(
                f"UID-1000 row not properly renamed: {new_row!r}"
            )

        # ── Step 6: filesystem integrity check ───────────────────────────
        if not self.fs.fsck_clean():
            raise RootfsFsckError("e2fsck reports errors after personalization")

        # ── Step 7: inject resize trigger into boot partition /cmdline.txt ─
        self._inject_cmdline()

    def _inject_cmdline(self) -> None:
        """Inject the AstromechOS first-boot resize init arg into /cmdline.txt.

        No-op when ``self.boot`` is ``None``.

        Raises
        ------
        CmdlineInjectionFailedError
            If reading or writing /cmdline.txt fails.
        """
        if self.boot is None:
            return
        try:
            cmdline = self.boot.read_bytes("/cmdline.txt")
        except Exception as e:
            raise CmdlineInjectionFailedError(
                f"Could not read /cmdline.txt from boot partition: {e}"
            ) from e
        new_cmdline = ensure_resize_init_in_cmdline(cmdline)
        if new_cmdline != cmdline:
            try:
                self.boot.write_bytes("/cmdline.txt", new_cmdline)
            except Exception as e:
                raise CmdlineInjectionFailedError(
                    f"Could not write /cmdline.txt to boot partition: {e}"
                ) from e
