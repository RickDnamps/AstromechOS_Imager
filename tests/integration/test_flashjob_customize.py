"""Integration tests for FlashJob's FAT customize phase.

Exercises FlashJob.run() with an in-memory FAT boot partition and asserts the
cloud-init NoCloud first-boot customization: user-data (account + password),
meta-data (unique instance-id), the `resize` + `ds=nocloud;i=...` cmdline
tokens, and the AstromechOS firstboot bundle.
"""
from __future__ import annotations

import lzma
import re
import struct
import threading
from pathlib import Path

import pytest

from astromechos_imager.core.cloud_init_generator import RESIZE_TOKEN
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


def _assert_cloud_init(fake_boot):
    # cloud-init seed: meta-data (unique instance-id) + user-data (account).
    assert fake_boot.exists("/meta-data")
    md = fake_boot.files["/meta-data"].decode("ascii")
    m = re.search(r"instance-id:\s*(rpi-imager-\d+)", md)
    assert m, f"meta-data missing rpi-imager instance-id: {md!r}"
    instance_id = m.group(1)

    assert fake_boot.exists("/user-data")
    ud = fake_boot.files["/user-data"].decode("utf-8")
    assert ud.startswith("#cloud-config")
    assert "name: 'testuser'" in ud
    assert "type: hash" in ud and "$6$salt$fakehash" in ud

    # cmdline: native resize token + ds=nocloud pinned to the SAME instance-id,
    # and NONE of the dead mechanisms (init=, firstrun.sh trigger).
    toks = fake_boot.files["/cmdline.txt"].decode("ascii").split()
    assert toks.count(RESIZE_TOKEN) == 1
    assert f"ds=nocloud;i={instance_id}" in toks
    assert not any(t.startswith("init=") for t in toks)
    assert not any(t.startswith("systemd.") for t in toks)
    assert not fake_boot.exists("/firstrun.sh")


def test_master_writes_cloudinit_and_bundle(tmp_path, fake_platform_io, monkeypatch):
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
    _assert_cloud_init(fake_boot)
    assert fake_boot.exists("/ASTROMECH_FIRSTBOOT_READY")
    assert fake_boot.exists("/astromech_secrets/init_config.json")
    assert fake_boot.exists("/astromech_secrets/authorized_keys")


def test_slave_also_writes_cloudinit(tmp_path, fake_platform_io, monkeypatch):
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
    _assert_cloud_init(fake_boot)


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
        _assert_cloud_init(fb)
        assert fb.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_without_account_resize_still_wired(tmp_path, fake_platform_io, monkeypatch):
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

    # No account → no user-data account block, but a valid NoCloud seed
    # (meta-data + #cloud-config) and the resize/ds=nocloud cmdline are still
    # wired so the rootfs grows on first boot.
    assert not fake_boot.exists("/firstrun.sh")
    assert fake_boot.exists("/meta-data")
    md = fake_boot.files["/meta-data"].decode("ascii")
    m = re.search(r"instance-id:\s*(rpi-imager-\d+)", md)
    assert m
    ud = fake_boot.files["/user-data"].decode("utf-8")
    assert ud.startswith("#cloud-config")
    assert "chpasswd" not in ud  # no account → no password block
    toks = fake_boot.files["/cmdline.txt"].decode("ascii").split()
    assert toks.count(RESIZE_TOKEN) == 1
    assert f"ds=nocloud;i={m.group(1)}" in toks
    assert not any(t.startswith("init=") for t in toks)
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


def test_success_ejects_media(tmp_path, fake_platform_io, monkeypatch):
    """On a successful flash the media is ejected so Windows drops the freshly
    written volumes (no "Format?" pop-up for the unreadable ext4 partition)."""
    fake_platform_io.add_drive(6, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)
    ejects: list[int] = []
    monkeypatch.setattr(fake_platform_io, "finalize_eject", lambda pid: ejects.append(pid))

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.MASTER,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, skip_verify=True,
    )
    assert job.run().ok
    assert ejects == [6], f"expected exactly one eject of drive 6 on success, got {ejects}"


def test_cancellation_skips_bundle_and_eject(tmp_path, fake_platform_io, monkeypatch):
    """Cancelled flash: no firstboot trigger written and no eject (the card is
    restored to exFAT instead)."""
    fake_platform_io.add_drive(5, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)
    ejects: list[int] = []
    monkeypatch.setattr(fake_platform_io, "finalize_eject", lambda pid: ejects.append(pid))
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
    assert ejects == [], "must not eject a cancelled (non-mbr_written) flash"


def test_flash_brackets_automount_disable_enable(tmp_path, fake_platform_io, monkeypatch):
    """The flash disables Windows automount up front and re-enables it in the
    finally — killing the post-flash 'Format this disk?' pop-up without ever
    leaving the operator's system with automount off."""
    fake_platform_io.add_drive(8, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)
    calls: list[str] = []
    monkeypatch.setattr(fake_platform_io, "disable_automount",
                        lambda: (calls.append("disable"), True)[1], raising=False)
    monkeypatch.setattr(fake_platform_io, "enable_automount",
                        lambda: calls.append("enable"), raising=False)

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.MASTER,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, skip_verify=True,
    )
    assert job.run().ok
    assert calls == ["disable", "enable"], f"expected disable→enable bracket, got {calls}"


def test_automount_reenabled_even_on_cancel(tmp_path, fake_platform_io, monkeypatch):
    """Even a cancelled flash must re-enable automount (it lives in the finally)."""
    fake_platform_io.add_drive(9, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)
    calls: list[str] = []
    monkeypatch.setattr(fake_platform_io, "disable_automount",
                        lambda: (calls.append("disable"), True)[1], raising=False)
    monkeypatch.setattr(fake_platform_io, "enable_automount",
                        lambda: calls.append("enable"), raising=False)
    cancel = threading.Event()
    cancel.set()

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.MASTER,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, skip_verify=True, cancel_event=cancel,
    )
    job.run()
    assert "enable" in calls, f"automount must be re-enabled even on cancel, got {calls}"
