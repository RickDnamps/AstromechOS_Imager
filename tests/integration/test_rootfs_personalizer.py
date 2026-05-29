"""Tests for RootfsPersonalizer.

Contains:
  - Unit tests using FakeRootfs (no WSL / ext4 required)
  - Integration tests using Ext4DebugfsBackend against the ext4 fixture via WSL
    (skipped if WSL or fixture unavailable)
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
from astromechos_imager.core.rootfs_personalizer import RootfsPersonalizer

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


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests — require WSL + ext4 fixture
# ─────────────────────────────────────────────────────────────────────────────

FIXTURE = Path("tests/poc/fixture.ext4.img").absolute()
_WSL_AVAILABLE = shutil.which("wsl") is not None
_FIXTURE_AVAILABLE = FIXTURE.exists()


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
        username="artoo",
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
        assert uid_row.name == "artoo"
        assert uid_row.home == "/home/artoo"

        # Assert /home/artoo/welcome.txt still accessible
        welcome = bk.read_bytes("/home/artoo/welcome.txt")
        assert welcome.strip() == b"hello from pi"

        # Assert e2fsck clean
        assert bk.fsck_clean() is True
    finally:
        bk.close()
