"""Integration tests for FlashJob rootfs personalization wiring (Task 5.5.4).

Uses FakePlatformIO + FakeRootfs + FakeBootPartition (all in-memory) to
exercise FlashJob.run() with linux_account set, asserting that:
  - rootfs rename happened
  - /cmdline.txt got the resize init arg
  - firstboot bundle was written
  - when linux_account=None, rootfs is NOT touched
"""
from __future__ import annotations

import lzma
import struct
import threading
from pathlib import Path

import pytest

from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, LinuxAccount, Role
from astromechos_imager.core.orchestrator import FlashJob, FlashJobResult
from astromechos_imager.core.rootfs_personalizer import RESIZE_INIT_ARG

pytestmark = pytest.mark.integration

VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"

STOCK_CMDLINE = (
    b"console=serial0,115200 console=tty1 root=PARTUUID=6c586e13-02 "
    b"rootfstype=ext4 fsck.repair=yes rootwait quiet splash\n"
)

_PASSWD_BYTES = (
    b"root:x:0:0:root:/root:/bin/bash\n"
    b"pi:x:1000:1000:,,,:/home/pi:/bin/bash\n"
)
_SHADOW_BYTES = (
    b"root:*:19000:0:99999:7:::\n"
    b"pi:OLD_HASH:19000:0:99999:7:::\n"
)
_GROUP_BYTES = b"root:x:0:\npi:x:1000:\nsudo:x:27:pi\n"


# ─────────────────────────────────────────────────────────────────────────────
# Fake infrastructure
# ─────────────────────────────────────────────────────────────────────────────


class FakeRootfsPartition:
    """In-memory RootfsPartition that records personalization operations."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {
            "/etc/passwd": _PASSWD_BYTES,
            "/etc/shadow": _SHADOW_BYTES,
            "/etc/group": _GROUP_BYTES,
        }
        self.dirs: set[str] = {"/home/pi"}
        self.fsck_result: bool = True

    def read_bytes(self, path: str) -> bytes:
        return self.files[path]

    def write_bytes(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def rename(self, src: str, dst: str) -> None:
        if src in self.dirs:
            self.dirs.discard(src)
            self.dirs.add(dst)

    def fsck_clean(self) -> bool:
        return self.fsck_result

    def close(self) -> None:
        pass


class FakeBootPartitionForFlash:
    """In-memory BootPartition for FlashJob tests."""

    def __init__(self, cmdline: bytes = STOCK_CMDLINE) -> None:
        self.files: dict[str, bytes] = {"/cmdline.txt": cmdline}
        self.dirs: set[str] = {"/"}

    def write_bytes(self, path: str, data: bytes) -> None:
        parent = "/" + "/".join(path.lstrip("/").split("/")[:-1])
        parent = parent.rstrip("/") or "/"
        if parent not in self.dirs:
            raise FileNotFoundError(f"parent {parent} missing")
        self.files[path] = data

    def read_bytes(self, path: str) -> bytes:
        return self.files[path]

    def mkdir(self, path: str) -> None:
        self.dirs.add(path)

    def exists(self, path: str) -> bool:
        return path in self.files or path in self.dirs

    def close(self) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# MBR builders
# ─────────────────────────────────────────────────────────────────────────────


def _make_pi_os_mbr() -> bytes:
    """Build a Pi OS-style MBR: FAT32 (0x0C) + Linux (0x83)."""
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    # Entry 0: FAT32 boot
    e0 = bytearray(16)
    e0[4] = 0x0C
    struct.pack_into("<I", e0, 8, 2048)
    struct.pack_into("<I", e0, 12, 32768)
    mbr[446:462] = bytes(e0)
    # Entry 1: Linux rootfs
    e1 = bytearray(16)
    e1[4] = 0x83
    struct.pack_into("<I", e1, 8, 34816)
    struct.pack_into("<I", e1, 12, 163840)
    mbr[462:478] = bytes(e1)
    return bytes(mbr)


def _make_no_linux_mbr() -> bytes:
    """Build an MBR with only a FAT32 partition (no Linux partition)."""
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    e0 = bytearray(16)
    e0[4] = 0x0C
    struct.pack_into("<I", e0, 8, 2048)
    struct.pack_into("<I", e0, 12, 32768)
    mbr[446:462] = bytes(e0)
    return bytes(mbr)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _mbr_payload(mbr: bytes, payload_extra: bytes = b"") -> bytes:
    out = bytearray(mbr)
    # pad to at least 512 * 1024 (512 KB)
    target = max(len(out), 512 * 1024)
    if len(out) < target:
        out.extend(b"\x00" * (target - len(out)))
    return bytes(out)


def _make_cfg() -> FirstbootConfig:
    return FirstbootConfig(
        authorized_keys=[VALID_KEY],
        imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_flashjob_with_linux_account_touches_rootfs_and_boot(
    tmp_path, fake_platform_io, monkeypatch
):
    """FlashJob with linux_account set: rootfs renamed + cmdline injected + bundle written."""
    payload = _mbr_payload(_make_pi_os_mbr())
    img = tmp_path / "master.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(3, size=len(payload) + 1024)

    cfg = _make_cfg()
    pair = generate_ed25519()
    acc = LinuxAccount(
        username="artoo",
        cleartext_password="test123",
        crypt_sha512="$6$salt$fakehash",
    )

    fake_rootfs = FakeRootfsPartition()
    fake_boot = FakeBootPartitionForFlash(STOCK_CMDLINE)

    # Monkeypatch the boot partition open to return our fake boot
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open",
        lambda *a, **kw: fake_boot,
    )
    # Monkeypatch the rootfs backend constructor
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._open_rootfs_partition",
        lambda *a, **kw: fake_rootfs,
    )

    job = FlashJob(
        platform_io=fake_platform_io,
        image_path=img,
        target=fake_platform_io.enumerate_removable_drives()[0],
        role=Role.MASTER,
        firstboot_config=cfg,
        master_pair=pair,
        linux_account=acc,
        skip_verify=True,
    )
    result = job.run()
    assert result.ok, f"FlashJob failed: {result.error}"

    # Rootfs was personalized
    assert b"artoo:x:1000" in fake_rootfs.files["/etc/passwd"]
    assert b"pi:x:1000" not in fake_rootfs.files["/etc/passwd"]

    # /cmdline.txt got the resize init arg
    assert RESIZE_INIT_ARG.encode("ascii") in fake_boot.files["/cmdline.txt"]

    # Firstboot bundle was written (trigger marker is last)
    assert fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY")
    assert fake_boot.exists("/astromech_secrets/init_config.json")
    assert fake_boot.exists("/astromech_secrets/authorized_keys")


def test_flashjob_without_linux_account_skips_rootfs(
    tmp_path, fake_platform_io, monkeypatch
):
    """FlashJob without linux_account: rootfs NOT touched, boot bundle written."""
    payload = _mbr_payload(_make_pi_os_mbr())
    img = tmp_path / "master.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(4, size=len(payload) + 1024)

    cfg = _make_cfg()
    pair = generate_ed25519()

    fake_rootfs = FakeRootfsPartition()
    fake_boot = FakeBootPartitionForFlash(STOCK_CMDLINE)

    open_rootfs_calls: list[str] = []

    def _fake_open_rootfs(*a, **kw):
        open_rootfs_calls.append("called")
        return fake_rootfs

    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open",
        lambda *a, **kw: fake_boot,
    )
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._open_rootfs_partition",
        _fake_open_rootfs,
    )

    job = FlashJob(
        platform_io=fake_platform_io,
        image_path=img,
        target=fake_platform_io.enumerate_removable_drives()[0],
        role=Role.MASTER,
        firstboot_config=cfg,
        master_pair=pair,
        linux_account=None,
        skip_verify=True,
    )
    result = job.run()
    assert result.ok, f"FlashJob failed: {result.error}"

    # Rootfs NOT opened
    assert open_rootfs_calls == []

    # Original passwd file untouched (pi still there)
    assert b"pi:x:1000" in fake_rootfs.files["/etc/passwd"]

    # /cmdline.txt NOT modified (no linux_account → no personalizer)
    assert RESIZE_INIT_ARG.encode("ascii") not in fake_boot.files["/cmdline.txt"]

    # Bundle still written
    assert fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_flashjob_cancellation_before_rootfs_skips_bundle(
    tmp_path, fake_platform_io, monkeypatch
):
    """Cancellation before rootfs step: trigger marker absent."""
    payload = _mbr_payload(_make_pi_os_mbr())
    img = tmp_path / "master.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(5, size=len(payload) + 1024)

    cfg = _make_cfg()
    pair = generate_ed25519()
    acc = LinuxAccount(
        username="artoo",
        cleartext_password="test123",
        crypt_sha512="$6$salt$fakehash",
    )

    cancel = threading.Event()
    cancel.set()  # cancel immediately

    fake_boot = FakeBootPartitionForFlash(STOCK_CMDLINE)

    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open",
        lambda *a, **kw: fake_boot,
    )
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._open_rootfs_partition",
        lambda *a, **kw: FakeRootfsPartition(),
    )

    job = FlashJob(
        platform_io=fake_platform_io,
        image_path=img,
        target=fake_platform_io.enumerate_removable_drives()[0],
        role=Role.MASTER,
        firstboot_config=cfg,
        master_pair=pair,
        linux_account=acc,
        skip_verify=True,
        cancel_event=cancel,
    )
    result = job.run()
    # Result is ok=True (cancelled FlashJob completes with bytes written=0 or similar)
    # but ASTROMECH_FIRSTBOOT_READY should NOT be written
    assert not fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY"), (
        "Trigger marker written despite cancellation"
    )
