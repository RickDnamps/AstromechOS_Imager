"""Integration tests for FlashJob's FAT customize phase.

Exercises FlashJob.run() with an in-memory FAT boot partition and asserts the
first-boot customization: /firstrun.sh (account setup), the systemd.run
trigger + rootfs auto-resize arg in cmdline.txt, and the firstboot bundle.
"""
from __future__ import annotations

import lzma
import struct
import threading
from pathlib import Path

import pytest

from astromechos_imager.core.cmdline_resize import RESIZE_INIT_ARG
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, LinuxAccount, Role
from astromechos_imager.core.orchestrator import FlashJob, PairFlashJob

pytestmark = pytest.mark.integration

VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"
STOCK_CMDLINE = (
    b"console=serial0,115200 console=tty1 root=PARTUUID=6c586e13-02 "
    b"rootfstype=ext4 fsck.repair=yes rootwait quiet splash\n"
)
ACC = LinuxAccount(username="testuser", cleartext_password="test123",
                   crypt_sha512="$6$salt$fakehash")


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


def _make_pi_os_mbr() -> bytes:
    """Pi OS-style MBR: FAT32 (0x0C) boot + Linux (0x83) rootfs."""
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    e0 = bytearray(16); e0[4] = 0x0C
    struct.pack_into("<I", e0, 8, 2048); struct.pack_into("<I", e0, 12, 32768)
    mbr[446:462] = bytes(e0)
    e1 = bytearray(16); e1[4] = 0x83
    struct.pack_into("<I", e1, 8, 34816); struct.pack_into("<I", e1, 12, 163840)
    mbr[462:478] = bytes(e1)
    return bytes(mbr)


def _mbr_payload(mbr: bytes) -> bytes:
    out = bytearray(mbr)
    out.extend(b"\x00" * (512 * 1024 - len(out)))
    return bytes(out)


def _make_cfg() -> FirstbootConfig:
    return FirstbootConfig(
        authorized_keys=[VALID_KEY],
        imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"),
    )


def _patch_boot(monkeypatch, fake_boot):
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open",
        lambda *a, **kw: fake_boot,
    )


def _img(tmp_path, name) -> Path:
    p = tmp_path / name
    p.write_bytes(lzma.compress(_mbr_payload(_make_pi_os_mbr())))
    return p


def _assert_firstrun(fake_boot):
    assert fake_boot.exists("/firstrun.sh")
    fr = fake_boot.files["/firstrun.sh"].decode("utf-8")
    assert "testuser" in fr
    assert "userconf" in fr and "chpasswd -e" in fr
    assert "rm -f /boot/firstrun.sh" in fr
    cmdline = fake_boot.files["/cmdline.txt"].decode("ascii")
    assert cmdline.split().count(RESIZE_INIT_ARG) == 1
    assert "systemd.run=/boot/firstrun.sh" in cmdline


def test_master_writes_firstrun_resize_and_bundle(tmp_path, fake_platform_io, monkeypatch):
    fake_platform_io.add_drive(3, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.MASTER,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, skip_verify=True,
    )
    result = job.run()
    assert result.ok, f"FlashJob failed: {result.error}"
    _assert_firstrun(fake_boot)
    assert fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY")
    assert fake_boot.exists("/astromech_secrets/init_config.json")
    assert fake_boot.exists("/astromech_secrets/authorized_keys")


def test_slave_also_writes_firstrun_and_resize(tmp_path, fake_platform_io, monkeypatch):
    fake_platform_io.add_drive(4, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "s.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.SLAVE,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, skip_verify=True,
    )
    result = job.run()
    assert result.ok, f"FlashJob (SLAVE) failed: {result.error}"
    _assert_firstrun(fake_boot)


def test_pair_customizes_both_cards(tmp_path, fake_platform_io, monkeypatch):
    fake_platform_io.add_drive(10, size=512 * 1024 + 1024)
    fake_platform_io.add_drive(11, size=512 * 1024 + 1024)
    fake_boot_master = FakeBootPartitionForFlash()
    fake_boot_slave = FakeBootPartitionForFlash()

    def _route_boot(platform_io=None, physical_drive_id=None, *a, **kw):
        return fake_boot_master if physical_drive_id == 10 else fake_boot_slave

    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open", _route_boot,
    )
    drives = {d.physical_drive_id: d for d in fake_platform_io.enumerate_removable_drives()}
    job = PairFlashJob(
        platform_io=fake_platform_io,
        master_image=_img(tmp_path, "m.img.xz"), master_target=drives[10],
        slave_image=_img(tmp_path, "s.img.xz"), slave_target=drives[11],
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, parallel=False, skip_verify=True,
    )
    result = job.run()
    assert result.master.ok and result.slave.ok, (
        f"PairFlashJob failed: master={result.master.error!r} slave={result.slave.error!r}"
    )
    for fb in (fake_boot_master, fake_boot_slave):
        _assert_firstrun(fb)
        assert fb.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_without_account_no_firstrun_but_resize_present(tmp_path, fake_platform_io, monkeypatch):
    fake_platform_io.add_drive(4, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.MASTER,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=None, skip_verify=True,
    )
    result = job.run()
    assert result.ok, f"FlashJob failed: {result.error}"

    # No account → no firstrun.sh / no trigger, but resize is still wired.
    assert not fake_boot.exists("/firstrun.sh")
    cmdline = fake_boot.files["/cmdline.txt"].decode("ascii")
    assert "systemd.run=/boot/firstrun.sh" not in cmdline
    assert cmdline.split().count(RESIZE_INIT_ARG) == 1
    assert fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_preflight_failure_aborts_before_touching_card(tmp_path, fake_platform_io, monkeypatch):
    """A preflight failure aborts before any destructive device access — no
    lock/dismount, no partition wipe, card untouched."""
    from astromechos_imager.core.errors import DriveNotFoundError

    fake_platform_io.add_drive(9, size=512 * 1024 + 1024)
    touched: list[str] = []
    orig_open = fake_platform_io.open_raw_device
    orig_lock = fake_platform_io.lock_and_dismount
    monkeypatch.setattr(fake_platform_io, "open_raw_device",
                        lambda *a, **kw: (touched.append("open"), orig_open(*a, **kw))[1])
    monkeypatch.setattr(fake_platform_io, "lock_and_dismount",
                        lambda *a, **kw: (touched.append("lock"), orig_lock(*a, **kw))[1])
    monkeypatch.setattr(
        FlashJob, "_preflight",
        lambda self: (_ for _ in ()).throw(DriveNotFoundError("simulated preflight failure")),
    )

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.MASTER,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, skip_verify=True,
    )
    result = job.run()
    assert not result.ok
    assert isinstance(result.error, DriveNotFoundError)
    assert result.error.sd_state == "SAFE"
    assert touched == [], f"preflight failure still touched the device: {touched}"


def test_cancellation_skips_bundle(tmp_path, fake_platform_io, monkeypatch):
    fake_platform_io.add_drive(5, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)
    cancel = threading.Event()
    cancel.set()

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.MASTER,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, skip_verify=True, cancel_event=cancel,
    )
    job.run()
    assert not fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY")
