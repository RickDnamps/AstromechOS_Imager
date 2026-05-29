"""RootfsPersonalizer — orchestrates the 4-step cold modification of a rootfs.

Per design spec §2.2.1:
  1. Rename the UID-1000 entry in /etc/passwd (name + home).
  2. Rename + replace password hash in /etc/shadow.
  3. Rename primary group + update group memberships in /etc/group.
  4. Rename /home/<old> → /home/<new> in the filesystem.

Then self-validates by re-reading /etc/passwd and runs e2fsck.
"""
from __future__ import annotations

from astromechos_imager.core.errors import (
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
from astromechos_imager.core.platform_io import RootfsPartition


class RootfsPersonalizer:
    """Orchestrate the 4-step cold rename of the UID-1000 Linux user.

    Parameters
    ----------
    account:
        The target account specification (username + crypt_sha512 hash).
    fs:
        A ``RootfsPartition`` backend providing read/write/rename/fsck on the
        ext4 rootfs partition.
    """

    def __init__(self, account: LinuxAccount, fs: RootfsPartition) -> None:
        self.account = account
        self.fs = fs

    def apply(self) -> None:
        """Perform all four modification steps, then self-validate and fsck.

        Idempotent: if UID-1000 already has ``self.account.username``, skips
        the rename steps and only runs fsck.

        Raises
        ------
        UidNotFoundError
            If no UID-1000 row exists in /etc/passwd.
        RootfsSelfValidationFailedError
            If the post-write re-read shows unexpected UID-1000 state.
        RootfsFsckError
            If e2fsck reports errors.
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
