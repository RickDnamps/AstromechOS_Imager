"""Unit tests for RootfsPersonalizer and ensure_resize_init_in_cmdline.

Contains:
  - Pure unit tests for ensure_resize_init_in_cmdline helper
  - FakeRootfs + FakeBootPartition pair tests for RootfsPersonalizer.apply()
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from astromechos_imager.core.errors import (
    CmdlineInjectionFailedError,
    RootfsFsckError,
    UidNotFoundError,
)
from astromechos_imager.core.models import LinuxAccount
from astromechos_imager.core.rootfs_personalizer import (
    RESIZE_INIT_ARG,
    RootfsPersonalizer,
    ensure_resize_init_in_cmdline,
)

# ─────────────────────────────────────────────────────────────────────────────
# FakeRootfs — in-memory filesystem for unit tests
# ─────────────────────────────────────────────────────────────────────────────


class FakeRootfs:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {
            "/etc/passwd": (
                b"root:x:0:0:root:/root:/bin/bash\n"
                b"pi:x:1000:1000:,,,:/home/pi:/bin/bash\n"
            ),
            "/etc/shadow": (
                b"root:*:19000:0:99999:7:::\n"
                b"pi:OLD_HASH:19000:0:99999:7:::\n"
            ),
            "/etc/group": b"root:x:0:\npi:x:1000:\nsudo:x:27:pi\n",
        }
        self.dirs: set[str] = {"/home/pi"}
        self.fsck_result: bool = True

    def read_bytes(self, p: str) -> bytes:
        return self.files[p]

    def write_bytes(self, p: str, d: bytes) -> None:
        self.files[p] = d

    def rename(self, src: str, dst: str) -> None:
        if src in self.dirs:
            self.dirs.discard(src)
            self.dirs.add(dst)
        elif src in self.files:
            self.files[dst] = self.files.pop(src)

    def fsck_clean(self) -> bool:
        return self.fsck_result

    def close(self) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# FakeBootPartition — in-memory BootPartition for unit tests
# ─────────────────────────────────────────────────────────────────────────────

STOCK_CMDLINE = (
    b"console=serial0,115200 console=tty1 root=PARTUUID=6c586e13-02 "
    b"rootfstype=ext4 fsck.repair=yes rootwait quiet splash\n"
)


class FakeBootPartition:
    def __init__(self, cmdline: bytes = STOCK_CMDLINE) -> None:
        self.files: dict[str, bytes] = {"/cmdline.txt": cmdline}
        self.dirs: set[str] = {"/"}
        self.read_raises: Exception | None = None
        self.write_raises: Exception | None = None

    def read_bytes(self, path: str) -> bytes:
        if self.read_raises is not None:
            raise self.read_raises
        return self.files[path]

    def write_bytes(self, path: str, data: bytes) -> None:
        if self.write_raises is not None:
            raise self.write_raises
        self.files[path] = data

    def mkdir(self, path: str) -> None:
        self.dirs.add(path)

    def exists(self, path: str) -> bool:
        return path in self.files or path in self.dirs

    def close(self) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for ensure_resize_init_in_cmdline
# ─────────────────────────────────────────────────────────────────────────────


def test_empty_input_appends_arg() -> None:
    """Empty input → just the init arg with trailing newline."""
    result = ensure_resize_init_in_cmdline(b"")
    assert result == (RESIZE_INIT_ARG + "\n").encode("ascii")


def test_arg_appended_when_absent() -> None:
    """Stock Pi OS cmdline without the arg → arg appended, single trailing newline."""
    cmdline = b"console=serial0,115200 console=tty1 rootwait quiet\n"
    result = ensure_resize_init_in_cmdline(cmdline)
    assert result.endswith(b"\n")
    assert RESIZE_INIT_ARG.encode("ascii") in result
    # Only ONE trailing newline
    assert not result.endswith(b"\n\n")
    # All original args still present
    assert b"console=serial0,115200" in result
    assert b"rootwait" in result


def test_arg_not_duplicated_when_present() -> None:
    """If the arg is already present, return the input verbatim (byte-identical)."""
    cmdline = f"console=tty1 {RESIZE_INIT_ARG} rootwait\n".encode("ascii")
    result = ensure_resize_init_in_cmdline(cmdline)
    assert result is cmdline  # exact same object — returned verbatim


def test_idempotent_no_trailing_newline() -> None:
    """Input without trailing newline → newline added in output."""
    cmdline = b"console=tty1 rootwait"
    result = ensure_resize_init_in_cmdline(cmdline)
    assert result.endswith(b"\n")
    assert RESIZE_INIT_ARG.encode("ascii") in result


def test_trailing_newline_preserved() -> None:
    """Input with trailing newline produces output with exactly one trailing newline."""
    cmdline = b"console=tty1 rootwait\n"
    result = ensure_resize_init_in_cmdline(cmdline)
    assert result.endswith(b"\n")
    assert not result.endswith(b"\n\n")


def test_multiple_spaces_normalized() -> None:
    """Multiple spaces between args are normalized to single spaces (split/join side effect)."""
    cmdline = b"console=tty1   rootwait\n"
    result = ensure_resize_init_in_cmdline(cmdline)
    # split+join normalizes spaces
    assert b"  " not in result


def test_arg_already_present_is_exact_object() -> None:
    """Verbatim return check: result is the identical object when arg already present."""
    cmdline = f"{RESIZE_INIT_ARG}\n".encode("ascii")
    result = ensure_resize_init_in_cmdline(cmdline)
    assert result is cmdline


@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("C",), blacklist_characters="=\n\r"),
        min_size=1,
        max_size=200,
    )
)
@settings(max_examples=100)
def test_double_application_idempotent(text: str) -> None:
    """Property: for any cmdline not containing the resize arg, calling twice == calling once."""
    # Exclude inputs that already contain the resize arg
    if RESIZE_INIT_ARG in text:
        return
    cmdline = text.strip().encode("ascii", errors="replace")
    first = ensure_resize_init_in_cmdline(cmdline)
    second = ensure_resize_init_in_cmdline(first)
    assert first == second


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for RootfsPersonalizer.apply() with fake boot partition
# ─────────────────────────────────────────────────────────────────────────────


def _make_account() -> LinuxAccount:
    return LinuxAccount(
        username="artoo",
        cleartext_password="x",
        crypt_sha512="$6$salt$hash",
    )


def test_apply_injects_cmdline_arg() -> None:
    """apply() with stock cmdline → cmdline.txt gets the init= arg appended."""
    acc = _make_account()
    fs = FakeRootfs()
    boot = FakeBootPartition(STOCK_CMDLINE)
    RootfsPersonalizer(acc, fs, boot).apply()

    result = boot.files["/cmdline.txt"]
    assert RESIZE_INIT_ARG.encode("ascii") in result


def test_apply_cmdline_already_has_arg_unchanged() -> None:
    """apply() when cmdline already has the arg → file is byte-identical."""
    acc = _make_account()
    fs = FakeRootfs()
    cmdline_with_arg = f"console=tty1 {RESIZE_INIT_ARG} rootwait\n".encode("ascii")
    boot = FakeBootPartition(cmdline_with_arg)
    RootfsPersonalizer(acc, fs, boot).apply()

    # The file content is unchanged (idempotent)
    result = boot.files["/cmdline.txt"]
    assert result == cmdline_with_arg


def test_apply_boot_read_raises_cmdline_error() -> None:
    """boot.read_bytes raising → CmdlineInjectionFailedError propagated."""
    acc = _make_account()
    fs = FakeRootfs()
    boot = FakeBootPartition()
    boot.read_raises = OSError("disk error")
    with pytest.raises(CmdlineInjectionFailedError, match="Could not read"):
        RootfsPersonalizer(acc, fs, boot).apply()


def test_apply_boot_write_raises_cmdline_error() -> None:
    """boot.write_bytes raising (when write is needed) → CmdlineInjectionFailedError."""
    acc = _make_account()
    fs = FakeRootfs()
    boot = FakeBootPartition(STOCK_CMDLINE)  # stock → write will be triggered
    boot.write_raises = OSError("write error")
    with pytest.raises(CmdlineInjectionFailedError, match="Could not write"):
        RootfsPersonalizer(acc, fs, boot).apply()


def test_apply_also_renames_user_with_boot() -> None:
    """apply() still performs rootfs rename steps when boot is provided."""
    acc = _make_account()
    fs = FakeRootfs()
    boot = FakeBootPartition(STOCK_CMDLINE)
    RootfsPersonalizer(acc, fs, boot).apply()

    assert b"artoo:x:1000:1000:,,,:/home/artoo:/bin/bash" in fs.files["/etc/passwd"]
    assert b"artoo:$6$salt$hash:" in fs.files["/etc/shadow"]
    assert "/home/artoo" in fs.dirs
    assert RESIZE_INIT_ARG.encode("ascii") in boot.files["/cmdline.txt"]


def test_personalizer_renames_and_validates() -> None:
    """Legacy test: RootfsPersonalizer still works with 2-arg form (boot=None)."""
    acc = LinuxAccount(
        username="artoo",
        cleartext_password="x",
        crypt_sha512="$6$salt$hash",
    )
    fs = FakeRootfs()
    RootfsPersonalizer(acc, fs).apply()

    # /etc/passwd: UID-1000 row fully renamed
    assert b"artoo:x:1000:1000:,,,:/home/artoo:/bin/bash" in fs.files["/etc/passwd"]
    assert b"pi:x:1000" not in fs.files["/etc/passwd"]

    # /etc/shadow: name and hash replaced
    assert b"artoo:$6$salt$hash:" in fs.files["/etc/shadow"]
    assert b"pi:" not in fs.files["/etc/shadow"]

    # /etc/group: primary group renamed + memberships updated
    assert b"artoo:x:1000:" in fs.files["/etc/group"]
    assert b"pi:x:1000:" not in fs.files["/etc/group"]
    assert b"sudo:x:27:artoo" in fs.files["/etc/group"]

    # /home rename
    assert "/home/artoo" in fs.dirs
    assert "/home/pi" not in fs.dirs


def test_personalizer_idempotent_if_already_renamed() -> None:
    """If UID-1000 already has the target name, apply() should short-circuit."""
    acc = LinuxAccount(
        username="artoo",
        cleartext_password="x",
        crypt_sha512="$6$salt$hash",
    )
    fs = FakeRootfs()
    # Pre-rename the passwd file so old_user == target
    fs.files["/etc/passwd"] = (
        b"root:x:0:0:root:/root:/bin/bash\n"
        b"artoo:x:1000:1000:,,,:/home/artoo:/bin/bash\n"
    )
    # Shadow, group, dirs untouched — apply should not raise
    RootfsPersonalizer(acc, fs).apply()
    # Passwd still correct
    assert b"artoo:x:1000" in fs.files["/etc/passwd"]


def test_personalizer_raises_uid_not_found() -> None:
    """Should raise UidNotFoundError when no UID-1000 row exists."""
    acc = LinuxAccount(username="artoo", cleartext_password="x", crypt_sha512="$6$s$h")
    fs = FakeRootfs()
    fs.files["/etc/passwd"] = b"root:x:0:0:root:/root:/bin/bash\n"
    with pytest.raises(UidNotFoundError):
        RootfsPersonalizer(acc, fs).apply()


def test_personalizer_raises_fsck_error_on_idempotent_path() -> None:
    """Idempotent path still runs fsck and raises on failure."""
    acc = LinuxAccount(username="artoo", cleartext_password="x", crypt_sha512="$6$s$h")
    fs = FakeRootfs()
    fs.files["/etc/passwd"] = (
        b"root:x:0:0:root:/root:/bin/bash\n"
        b"artoo:x:1000:1000:,,,:/home/artoo:/bin/bash\n"
    )
    fs.fsck_result = False
    with pytest.raises(RootfsFsckError):
        RootfsPersonalizer(acc, fs).apply()


def test_personalizer_raises_fsck_error_after_rename() -> None:
    """RootfsFsckError raised when fsck fails after a successful rename."""
    acc = LinuxAccount(username="artoo", cleartext_password="x", crypt_sha512="$6$s$h")
    fs = FakeRootfs()
    fs.fsck_result = False
    with pytest.raises(RootfsFsckError):
        RootfsPersonalizer(acc, fs).apply()
