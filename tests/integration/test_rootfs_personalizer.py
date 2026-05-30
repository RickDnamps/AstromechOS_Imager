"""Tests for RootfsPersonalizer.

Contains:
  - Integration tests using Ext4DebugfsBackend against the ext4 fixture via WSL
    (skipped if WSL or fixture unavailable)
  - Integration test combining WSL ext4 backend with FakeBootPartition to verify
    the Phase 5.5.3 cmdline injection step
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from astromechos_imager.core.errors import (
    RootfsFsckError,
    RootfsModError,
    UidNotFoundError,
)
from astromechos_imager.core.models import LinuxAccount
from astromechos_imager.core.passwd_files import parse_passwd
from astromechos_imager.core.rootfs import Ext4DebugfsBackend, _win_to_wsl_path
from astromechos_imager.core.rootfs_personalizer import RESIZE_INIT_ARG, RootfsPersonalizer

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
# Unit tests (FakeRootfs — no WSL)
# ─────────────────────────────────────────────────────────────────────────────


def test_personalizer_renames_and_validates() -> None:
    acc = LinuxAccount(
        username="testuser",
        cleartext_password="x",
        crypt_sha512="$6$salt$hash",
    )
    fs = FakeRootfs()
    RootfsPersonalizer(acc, fs).apply()

    # /etc/passwd: UID-1000 row fully renamed
    assert b"testuser:x:1000:1000:,,,:/home/testuser:/bin/bash" in fs.files["/etc/passwd"]
    assert b"pi:x:1000" not in fs.files["/etc/passwd"]

    # /etc/shadow: name and hash replaced
    assert b"testuser:$6$salt$hash:" in fs.files["/etc/shadow"]
    assert b"pi:" not in fs.files["/etc/shadow"]

    # /etc/group: primary group renamed + memberships updated
    assert b"testuser:x:1000:" in fs.files["/etc/group"]
    assert b"pi:x:1000:" not in fs.files["/etc/group"]
    assert b"sudo:x:27:testuser" in fs.files["/etc/group"]

    # /home rename
    assert "/home/testuser" in fs.dirs
    assert "/home/pi" not in fs.dirs


def test_personalizer_idempotent_if_already_renamed() -> None:
    """If UID-1000 already has the target name, apply() should short-circuit."""
    acc = LinuxAccount(
        username="testuser",
        cleartext_password="x",
        crypt_sha512="$6$salt$hash",
    )
    fs = FakeRootfs()
    # Pre-rename the passwd file so old_user == target
    fs.files["/etc/passwd"] = (
        b"root:x:0:0:root:/root:/bin/bash\n"
        b"testuser:x:1000:1000:,,,:/home/testuser:/bin/bash\n"
    )
    # Shadow, group, dirs untouched — apply should not raise
    RootfsPersonalizer(acc, fs).apply()
    # Passwd still correct
    assert b"testuser:x:1000" in fs.files["/etc/passwd"]


def test_personalizer_raises_uid_not_found() -> None:
    """Should raise UidNotFoundError when no UID-1000 row exists."""
    acc = LinuxAccount(username="testuser", cleartext_password="x", crypt_sha512="$6$s$h")
    fs = FakeRootfs()
    fs.files["/etc/passwd"] = b"root:x:0:0:root:/root:/bin/bash\n"
    with pytest.raises(UidNotFoundError):
        RootfsPersonalizer(acc, fs).apply()


def test_personalizer_raises_fsck_error_on_idempotent_path() -> None:
    """Idempotent path still runs fsck and raises on failure."""
    acc = LinuxAccount(username="testuser", cleartext_password="x", crypt_sha512="$6$s$h")
    fs = FakeRootfs()
    fs.files["/etc/passwd"] = (
        b"root:x:0:0:root:/root:/bin/bash\n"
        b"testuser:x:1000:1000:,,,:/home/testuser:/bin/bash\n"
    )
    fs.fsck_result = False
    with pytest.raises(RootfsFsckError):
        RootfsPersonalizer(acc, fs).apply()


def test_personalizer_raises_fsck_error_after_rename() -> None:
    """RootfsFsckError raised when fsck fails after a successful rename."""
    acc = LinuxAccount(username="testuser", cleartext_password="x", crypt_sha512="$6$s$h")
    fs = FakeRootfs()
    fs.fsck_result = False
    with pytest.raises(RootfsFsckError):
        RootfsPersonalizer(acc, fs).apply()


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests — require WSL + ext4 fixture
# ─────────────────────────────────────────────────────────────────────────────

FIXTURE = Path("tests/poc/fixture.ext4.img").absolute()
_WSL_AVAILABLE = shutil.which("wsl") is not None
_FIXTURE_AVAILABLE = FIXTURE.exists()

STOCK_CMDLINE = (
    b"console=serial0,115200 console=tty1 root=PARTUUID=6c586e13-02 "
    b"rootfstype=ext4 fsck.repair=yes rootwait quiet splash\n"
)


class _FakeBootPartition:
    """Minimal in-memory BootPartition for integration combo tests."""

    def __init__(self, cmdline: bytes = STOCK_CMDLINE) -> None:
        self.files: dict[str, bytes] = {"/cmdline.txt": cmdline}
        self.dirs: set[str] = {"/"}

    def read_bytes(self, path: str) -> bytes:
        return self.files[path]

    def write_bytes(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def mkdir(self, path: str) -> None:
        self.dirs.add(path)

    def exists(self, path: str) -> bool:
        return path in self.files or path in self.dirs

    def close(self) -> None:
        pass


@pytest.mark.integration
@pytest.mark.skipif(
    not (_WSL_AVAILABLE and _FIXTURE_AVAILABLE),
    reason="WSL or ext4 fixture not available",
)
def test_personalizer_apply_integration(tmp_path: Path) -> None:
    """Full apply() against the ext4 fixture via WSL debugfs."""
    fix = tmp_path / "fixture.img"
    shutil.copy(FIXTURE, fix)

    bk = Ext4DebugfsBackend(
        image_path=_win_to_wsl_path(fix),
        offset_bytes=0,
        debugfs_exe=Path("/usr/sbin/debugfs"),
        e2fsck_exe=Path("/usr/sbin/e2fsck"),
        invoker=["wsl"],
    )
    acc = LinuxAccount(
        username="testuser",
        cleartext_password="test123",
        crypt_sha512="$6$salt$hash",
    )
    try:
        RootfsPersonalizer(acc, bk).apply()

        # Assert UID-1000 row fully renamed
        passwd_bytes = bk.read_bytes("/etc/passwd")
        rows = parse_passwd(passwd_bytes)
        uid_row = next((r for r in rows if r.uid == 1000), None)
        assert uid_row is not None, "No UID-1000 row after personalization"
        assert uid_row.name == "testuser"
        assert uid_row.home == "/home/testuser"

        # Assert /home/testuser/welcome.txt still accessible
        welcome = bk.read_bytes("/home/testuser/welcome.txt")
        assert welcome.strip() == b"hello from pi"

        # Assert e2fsck clean
        assert bk.fsck_clean() is True
    finally:
        bk.close()


@pytest.mark.integration
@pytest.mark.skipif(
    not (_WSL_AVAILABLE and _FIXTURE_AVAILABLE),
    reason="WSL or ext4 fixture not available",
)
def test_personalizer_apply_integration_with_boot_partition(tmp_path: Path) -> None:
    """apply() with WSL ext4 backend + FakeBootPartition: both rootfs and cmdline mutated.

    Phase 5.5.3 amendment: verifies that when a boot partition is passed to
    RootfsPersonalizer, the AstromechOS first-boot resize init arg is injected
    into /cmdline.txt in addition to the rootfs rename steps.
    """
    fix = tmp_path / "fixture.img"
    shutil.copy(FIXTURE, fix)

    bk = Ext4DebugfsBackend(
        image_path=_win_to_wsl_path(fix),
        offset_bytes=0,
        debugfs_exe=Path("/usr/sbin/debugfs"),
        e2fsck_exe=Path("/usr/sbin/e2fsck"),
        invoker=["wsl"],
    )
    boot = _FakeBootPartition(STOCK_CMDLINE)
    acc = LinuxAccount(
        username="testuser",
        cleartext_password="test123",
        crypt_sha512="$6$salt$hash",
    )
    try:
        RootfsPersonalizer(acc, bk, boot).apply()

        # Assert UID-1000 row fully renamed in rootfs
        passwd_bytes = bk.read_bytes("/etc/passwd")
        rows = parse_passwd(passwd_bytes)
        uid_row = next((r for r in rows if r.uid == 1000), None)
        assert uid_row is not None, "No UID-1000 row after personalization"
        assert uid_row.name == "testuser"
        assert uid_row.home == "/home/testuser"

        # Assert e2fsck clean
        assert bk.fsck_clean() is True

        # Assert cmdline.txt has the resize init arg injected
        cmdline = boot.files["/cmdline.txt"]
        assert RESIZE_INIT_ARG.encode("ascii") in cmdline
        # All original args preserved
        assert b"console=serial0,115200" in cmdline
        assert b"rootwait" in cmdline
    finally:
        bk.close()


@pytest.mark.integration
@pytest.mark.skipif(
    not (_WSL_AVAILABLE and _FIXTURE_AVAILABLE),
    reason="WSL or ext4 fixture not available",
)
def test_personalizer_apply_integration_cmdline_idempotent(tmp_path: Path) -> None:
    """apply() when /cmdline.txt already has the resize arg: file is not rewritten."""
    fix = tmp_path / "fixture.img"
    shutil.copy(FIXTURE, fix)

    bk = Ext4DebugfsBackend(
        image_path=_win_to_wsl_path(fix),
        offset_bytes=0,
        debugfs_exe=Path("/usr/sbin/debugfs"),
        e2fsck_exe=Path("/usr/sbin/e2fsck"),
        invoker=["wsl"],
    )
    cmdline_with_arg = f"console=tty1 {RESIZE_INIT_ARG} rootwait\n".encode("ascii")
    boot = _FakeBootPartition(cmdline_with_arg)
    acc = LinuxAccount(
        username="testuser",
        cleartext_password="test123",
        crypt_sha512="$6$salt$hash",
    )
    try:
        RootfsPersonalizer(acc, bk, boot).apply()

        # cmdline.txt unchanged (idempotent)
        result = boot.files["/cmdline.txt"]
        assert result == cmdline_with_arg
    finally:
        bk.close()
