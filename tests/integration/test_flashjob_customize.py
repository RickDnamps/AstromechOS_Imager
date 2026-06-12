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
from astromechos_imager.core.orchestrator import FlashJob

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
    e0 = bytearray(16)
    e0[4] = 0x0C
    struct.pack_into("<I", e0, 8, 2048)
    struct.pack_into("<I", e0, 12, 32768)
    mbr[446:462] = bytes(e0)
    e1 = bytearray(16)
    e1[4] = 0x83
    struct.pack_into("<I", e1, 8, 34816)
    struct.pack_into("<I", e1, 12, 163840)
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


# (test_pair_customizes_both_cards removed with PairFlashJob — the sequential
# master + slave single-job tests above cover both roles' customize paths.)


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


def test_flash_does_not_prezero_sector0(tmp_path, fake_platform_io, monkeypatch):
    """The flash must NOT wipe sector 0 before the streaming write.

    Field log 2026-06-10: pre-zeroing the partition table turns the card RAW
    for the whole write window, and a RAW card with a still-attached drive
    letter is exactly what makes Windows pop "Format this disk?". The silent
    path leaves sector 0 untouched and lets the deferred-MBR-last design carry
    the partition table. So the FIRST device write must NOT be an all-zero
    sector-0 wipe.
    """
    fake_platform_io.add_drive(7, size=512 * 1024 + 1024)
    fake_boot = FakeBootPartitionForFlash()
    _patch_boot(monkeypatch, fake_boot)

    writes: list[tuple[int, bool, int]] = []  # (offset, all_zero, length)
    orig_open = fake_platform_io.open_raw_device

    class _RecordingDev:
        def __init__(self, inner):
            self._inner = inner
            self.sector_size = getattr(inner, "sector_size", 512)
            self._h = getattr(inner, "_h", 0xF000)

        def write(self, offset, data):
            writes.append((offset, set(data) <= {0}, len(data)))
            return self._inner.write(offset, data)

        def read(self, offset, length):
            return self._inner.read(offset, length)

        def flush(self):
            self._inner.flush()

        def close(self):
            self._inner.close()

    monkeypatch.setattr(fake_platform_io, "open_raw_device",
                        lambda pid: _RecordingDev(orig_open(pid)))

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=fake_platform_io.enumerate_removable_drives()[0], role=Role.MASTER,
        firstboot_config=_make_cfg(), master_pair=generate_ed25519(),
        linux_account=ACC, skip_verify=True,
    )
    assert job.run().ok
    assert writes, "no writes recorded"
    # No early all-zero sector-0 wipe — the first write must NOT be a small
    # all-zero block at offset 0 (that was the RAW-card / pop-up regression).
    first_off, first_zero, first_len = writes[0]
    assert not (first_off == 0 and first_zero and first_len <= 4096), (
        f"flash must not pre-zero sector 0; first write was {writes[0]}"
    )


def test_wait_for_unmount_polls_until_letterless(tmp_path, fake_platform_io, monkeypatch):
    r"""Active-wait gate: keep force-dismounting + polling until the target disk
    is letter-less, so we never open \\.\PhysicalDrive while Windows still holds
    the freshly-inserted Slave (the 'Format this disk?' precondition)."""
    fake_platform_io.add_drive(12, size=512 * 1024 + 1024)
    target = fake_platform_io.enumerate_removable_drives()[0]
    state = {"polls": 0}

    def fake_letters(pid):
        state["polls"] += 1
        return ["K"] if state["polls"] <= 2 else []   # Windows releases after 2

    unmounts: list[str] = []
    monkeypatch.setattr(fake_platform_io, "letters_on_disk", fake_letters, raising=False)
    monkeypatch.setattr(fake_platform_io, "force_unmount_letter",
                        lambda letter: unmounts.append(letter), raising=False)

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=target, role=Role.MASTER, firstboot_config=_make_cfg(),
        master_pair=generate_ed25519(), linux_account=ACC, skip_verify=True,
    )
    job._wait_for_unmount(timeout_s=5.0, poll_s=0.01)
    assert unmounts == ["K", "K"], f"expected two force-unmounts of K, got {unmounts}"
    assert state["polls"] >= 3, "must poll until the disk reports no letter"


def test_wait_for_unmount_times_out_best_effort(tmp_path, fake_platform_io, monkeypatch):
    """If Windows never releases the letter, the gate proceeds best-effort
    (logs + returns) instead of blocking the flash forever — no regression."""
    fake_platform_io.add_drive(13, size=512 * 1024 + 1024)
    target = fake_platform_io.enumerate_removable_drives()[0]
    calls: list[str] = []
    monkeypatch.setattr(fake_platform_io, "letters_on_disk",
                        lambda pid: ["K"], raising=False)
    monkeypatch.setattr(fake_platform_io, "force_unmount_letter",
                        lambda letter: calls.append(letter), raising=False)

    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=target, role=Role.MASTER, firstboot_config=_make_cfg(),
        master_pair=generate_ed25519(), linux_account=ACC, skip_verify=True,
    )
    import time as _t
    t0 = _t.monotonic()
    job._wait_for_unmount(timeout_s=0.05, poll_s=0.01)
    assert _t.monotonic() - t0 < 3.0, "must not block forever on a stuck letter"
    assert calls, "force_unmount must be attempted before giving up"


def test_wait_for_unmount_noop_without_platform_hooks(tmp_path, fake_platform_io):
    """On platforms/fakes without the hooks (letters_on_disk/force_unmount_letter)
    the gate is a no-op and never blocks — the default fake has no such methods."""
    fake_platform_io.add_drive(14, size=512 * 1024 + 1024)
    target = fake_platform_io.enumerate_removable_drives()[0]
    job = FlashJob(
        platform_io=fake_platform_io, image_path=_img(tmp_path, "m.img.xz"),
        target=target, role=Role.MASTER, firstboot_config=_make_cfg(),
        master_pair=generate_ed25519(), linux_account=ACC, skip_verify=True,
    )
    job._wait_for_unmount(timeout_s=5.0, poll_s=0.01)  # returns immediately


def test_flash_disables_automount_and_does_not_reenable(tmp_path, fake_platform_io, monkeypatch):
    """The flash disables Windows automount up front and — critically — does
    NOT re-enable it per-card. Automount stays off for the whole session so
    Windows can't grab + probe the freshly-inserted Slave between cards and pop
    'Format this disk?'. The restore happens at app shutdown (aboutToQuit), not
    inside FlashJob.run()."""
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
    assert calls == ["disable"], (
        f"FlashJob must disable automount but NOT re-enable it per-card "
        f"(restore is app-shutdown scoped); got {calls}"
    )


def test_cancel_does_not_reenable_automount(tmp_path, fake_platform_io, monkeypatch):
    """A cancelled flash must NOT re-enable automount either — it stays off for
    the whole session (restored only at app shutdown). Re-enabling on cancel
    would re-open the between-cards window Windows uses to probe the Slave."""
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
    assert "enable" not in calls, (
        f"automount must stay disabled across a cancel (restored at app "
        f"shutdown, not in FlashJob); got {calls}"
    )
