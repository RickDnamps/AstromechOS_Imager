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
from astromechos_imager.core.orchestrator import FlashJob, FlashJobResult, PairFlashJob
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
        hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"),
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
        username="testuser",
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
    assert b"testuser:x:1000" in fake_rootfs.files["/etc/passwd"]
    assert b"pi:x:1000" not in fake_rootfs.files["/etc/passwd"]

    # /cmdline.txt got the resize init arg — exactly once. SD-fill safety
    # invariant: Pi OS first-boot rootfs auto-resize MUST be wired for the
    # Master card too, not just the Slave. Without it, the Master's rootfs
    # stays pinned at the Golden Image's ~3 GB and runs out of disk within
    # days. Idempotent: re-running apply() must not duplicate the arg.
    assert RESIZE_INIT_ARG.encode("ascii") in fake_boot.files["/cmdline.txt"]
    cmdline_text = fake_boot.files["/cmdline.txt"].decode("ascii")
    assert cmdline_text.split().count(RESIZE_INIT_ARG) == 1, (
        f"resize arg appears {cmdline_text.split().count(RESIZE_INIT_ARG)} times "
        f"in MASTER cmdline.txt — must be exactly 1"
    )

    # Firstboot bundle was written (trigger marker is last)
    assert fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY")
    assert fake_boot.exists("/astromech_secrets/init_config.json")
    assert fake_boot.exists("/astromech_secrets/authorized_keys")


def test_flashjob_slave_role_also_injects_resize_arg(
    tmp_path, fake_platform_io, monkeypatch
):
    """SD-fill safety lockdown: the Pi OS first-boot rootfs auto-resize
    arg MUST be injected for BOTH cards of a paired flash, not just the
    Master. Without it, the Slave's rootfs stays at the Golden Image's
    ~3 GB partition size and runs out of disk space within days. Per
    CLAUDE.md hard invariant: cold rootfs surgery is role-symmetric."""
    payload = _mbr_payload(_make_pi_os_mbr())
    img = tmp_path / "slave.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(4, size=len(payload) + 1024)

    cfg = _make_cfg()
    pair = generate_ed25519()
    acc = LinuxAccount(
        username="testuser",
        cleartext_password="test123",
        crypt_sha512="$6$salt$fakehash",
    )

    fake_rootfs = FakeRootfsPartition()
    fake_boot = FakeBootPartitionForFlash(STOCK_CMDLINE)

    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open",
        lambda *a, **kw: fake_boot,
    )
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._open_rootfs_partition",
        lambda *a, **kw: fake_rootfs,
    )

    job = FlashJob(
        platform_io=fake_platform_io,
        image_path=img,
        target=fake_platform_io.enumerate_removable_drives()[0],
        role=Role.SLAVE,
        firstboot_config=cfg,
        master_pair=pair,
        linux_account=acc,
        skip_verify=True,
    )
    result = job.run()
    assert result.ok, f"FlashJob (SLAVE) failed: {result.error}"

    # Rootfs personalization ran for slave too
    assert b"testuser:x:1000" in fake_rootfs.files["/etc/passwd"]

    # /cmdline.txt got the resize init arg — the critical lockdown
    assert RESIZE_INIT_ARG.encode("ascii") in fake_boot.files["/cmdline.txt"]
    # And exactly once (idempotent), even though apply() always touches it
    cmdline_text = fake_boot.files["/cmdline.txt"].decode("ascii")
    assert cmdline_text.split().count(RESIZE_INIT_ARG) == 1


def test_pair_flash_resize_arg_injected_on_both_cards(
    tmp_path, fake_platform_io, monkeypatch
):
    """End-to-end PairFlashJob symmetry lockdown.

    A real pair burn runs TWO ``FlashJob`` instances (sequentially or in
    parallel) with the SAME ``linux_account``. Each opens its OWN ext4
    rootfs + FAT32 boot partition. This test stubs both partitions per
    role and asserts that BOTH ``cmdline.txt`` files end up with the
    Pi-OS first-boot resize arg present and exactly once — i.e. the
    Pi-OS first-boot rootfs auto-resize is wired for BOTH cards, not
    just whichever one the FlashJob saw first. Without this guarantee,
    one half of the pair would run out of disk space within days while
    the other expanded fine.
    """
    payload = _mbr_payload(_make_pi_os_mbr())
    img_m = tmp_path / "master.img.xz"
    img_s = tmp_path / "slave.img.xz"
    compressed = lzma.compress(payload)
    img_m.write_bytes(compressed)
    img_s.write_bytes(compressed)
    fake_platform_io.add_drive(10, size=len(payload) + 1024)
    fake_platform_io.add_drive(11, size=len(payload) + 1024)

    cfg = _make_cfg()
    pair = generate_ed25519()
    acc = LinuxAccount(
        username="testuser",
        cleartext_password="test123",
        crypt_sha512="$6$salt$fakehash",
    )

    # Per-card partition fakes — one rootfs + one boot each, so we can
    # introspect them independently after the run.
    fake_rootfs_master = FakeRootfsPartition()
    fake_rootfs_slave  = FakeRootfsPartition()
    fake_boot_master   = FakeBootPartitionForFlash(STOCK_CMDLINE)
    fake_boot_slave    = FakeBootPartitionForFlash(STOCK_CMDLINE)

    # The orchestrator calls _bootpartition_open(platform_io,
    # physical_drive_id, mbr) positionally and _open_rootfs_partition with
    # raw_device_path=\\.\PHYSICALDRIVEN. Route each to its per-role fake:
    # master ⇒ id 10 ⇒ PHYSICALDRIVE10, slave ⇒ id 11.
    def _route_boot(platform_io=None, physical_drive_id=None, *a, **kw):
        return fake_boot_master if physical_drive_id == 10 else fake_boot_slave

    def _route_rootfs(*a, raw_device_path: str = "", **kw):
        return fake_rootfs_master if raw_device_path.endswith("10") else fake_rootfs_slave

    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open", _route_boot,
    )
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._open_rootfs_partition", _route_rootfs,
    )

    drives = {d.physical_drive_id: d for d in fake_platform_io.enumerate_removable_drives()}
    job = PairFlashJob(
        platform_io=fake_platform_io,
        master_image=img_m,
        master_target=drives[10],
        slave_image=img_s,
        slave_target=drives[11],
        firstboot_config=cfg,
        master_pair=pair,
        linux_account=acc,
        parallel=False,        # serial = deterministic per-side assertions
        skip_verify=True,
    )
    result = job.run()
    assert result.master.ok and result.slave.ok, (
        f"PairFlashJob failed: master={result.master.error!r} "
        f"slave={result.slave.error!r}"
    )

    # ── BOTH rootfs partitions personalized ──────────────────────────
    assert b"testuser:x:1000" in fake_rootfs_master.files["/etc/passwd"]
    assert b"testuser:x:1000" in fake_rootfs_slave.files["/etc/passwd"]

    # ── BOTH cmdline.txt files got the resize arg, exactly once each ─
    for role, fake_boot in (("MASTER", fake_boot_master), ("SLAVE", fake_boot_slave)):
        cmdline_bytes = fake_boot.files["/cmdline.txt"]
        assert RESIZE_INIT_ARG.encode("ascii") in cmdline_bytes, (
            f"{role}: resize arg missing from cmdline.txt"
        )
        count = cmdline_bytes.decode("ascii").split().count(RESIZE_INIT_ARG)
        assert count == 1, f"{role}: resize arg appears {count} times — must be exactly 1"

    # ── BOTH cards have the trigger marker (write order honoured) ────
    assert fake_boot_master.exists("/ASTROMECH_FIRSTBOOT_READY")
    assert fake_boot_slave.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_flashjob_without_linux_account_skips_rootfs(
    tmp_path, fake_platform_io, monkeypatch
):
    """FlashJob without linux_account: ext4 rootfs surgery is NOT performed,
    but the mandatory Pi-OS first-boot rootfs auto-resize arg IS still wired
    into /cmdline.txt.

    Decoupling lockdown (invariant #5): the resize injection is a FAT-only
    write and is independent of the (optional) UID-1000 cold surgery. It must
    run for EVERY card the Imager touches — even one with no account
    customization — so the card never stays pinned at the golden image's
    partition size. (Previously this was wrongly coupled to linux_account,
    which is also what hid the bug where a missing debugfs.exe silently
    skipped BOTH the rename AND the resize.)"""
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

    # Rootfs NOT opened (no ext4 cold surgery without an account)
    assert open_rootfs_calls == []

    # Original passwd file untouched (pi still there)
    assert b"pi:x:1000" in fake_rootfs.files["/etc/passwd"]

    # /cmdline.txt STILL gets the resize arg — exactly once. The resize is
    # decoupled from cold surgery and mandatory for every card (invariant #5).
    assert RESIZE_INIT_ARG.encode("ascii") in fake_boot.files["/cmdline.txt"]
    cmdline_text = fake_boot.files["/cmdline.txt"].decode("ascii")
    assert cmdline_text.split().count(RESIZE_INIT_ARG) == 1

    # Bundle still written
    assert fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_flashjob_resize_injected_even_when_debugfs_missing(
    tmp_path, fake_platform_io, monkeypatch
):
    """Regression (the real-robot bug): a missing debugfs.exe must NOT also
    skip the mandatory rootfs auto-resize.

    Field finding 2026-06: on the deployed cards the vendored e2fsprogs tools
    were absent, so the UID-1000 cold surgery was silently skipped — AND,
    because the resize injection used to live INSIDE the surgery, the resize
    arg was skipped too, pinning the rootfs at ~5 GB. This test simulates the
    missing tool (``_open_rootfs_partition`` raises FileNotFoundError) with an
    account set, and asserts the flash still succeeds and /cmdline.txt still
    carries the resize arg exactly once."""
    payload = _mbr_payload(_make_pi_os_mbr())
    img = tmp_path / "master.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(7, size=len(payload) + 1024)

    cfg = _make_cfg()
    pair = generate_ed25519()
    acc = LinuxAccount(
        username="testuser",
        cleartext_password="test123",
        crypt_sha512="$6$salt$fakehash",
    )

    fake_boot = FakeBootPartitionForFlash(STOCK_CMDLINE)

    def _raise_missing_debugfs(*a, **kw):
        # Mirrors subprocess.run on a non-existent debugfs.exe (WinError 2).
        raise FileNotFoundError(2, "The system cannot find the file specified", "debugfs.exe")

    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open",
        lambda *a, **kw: fake_boot,
    )
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._open_rootfs_partition",
        _raise_missing_debugfs,
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
    # Flash succeeds: cold surgery is skipped gracefully, the rest still runs.
    assert result.ok, f"FlashJob failed: {result.error}"

    # The UID-1000 rename did NOT happen (golden 'pi' user survives)...
    # ...but the MANDATORY resize arg IS present, exactly once.
    assert RESIZE_INIT_ARG.encode("ascii") in fake_boot.files["/cmdline.txt"]
    cmdline_text = fake_boot.files["/cmdline.txt"].decode("ascii")
    assert cmdline_text.split().count(RESIZE_INIT_ARG) == 1

    # Firstboot bundle still written (write order honoured)
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
        username="testuser",
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
