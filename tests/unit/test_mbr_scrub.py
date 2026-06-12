# tests/unit/test_mbr_scrub.py
"""MBR scrub contract (field log 2026-06-12, slave card pop-up).

IOCTL_DISK_DELETE_DRIVE_LAYOUT only clears partmgr's IN-MEMORY layout;
the old partition table stays physically on the card during the whole
streaming write (deferred-MBR design writes sector 0 last). A mid-write
shell re-query makes disk.sys re-read the still-valid old table, the old
volumes re-arrive, and a sticky MountedDevices binding re-attaches a
letter to a half-overwritten RAW filesystem — "Format this disk?".

The orchestrator therefore ZEROES the first bytes of the disk right
after open_raw_device and before the DiskWriter stream:

  1. the scrub is the FIRST write the device sees, at offset 0, all
     zeros, at least 4096 bytes (one 4Kn sector);
  2. the deferred-MBR write at the end restores real image bytes over
     the scrubbed region, so the final card content is byte-identical
     to the source image;
  3. a denied scrub write is non-fatal — the flash proceeds exactly as
     before the fix (best-effort defense, never a new failure mode).
"""
import lzma

from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role
from astromechos_imager.core.orchestrator import FlashJob

VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


class _RecordingDevice:
    """Pass-through proxy that records every write as (offset, len, all_zero)."""

    def __init__(self, inner, ops):
        self._inner = inner
        self._ops = ops

    def write(self, offset, data):
        self._ops.append((offset, len(data), data.count(0) == len(data)))
        return self._inner.write(offset, data)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _ScrubDeniedDevice(_RecordingDevice):
    """First write (the scrub) is denied, mimicking ERROR_ACCESS_DENIED."""

    def __init__(self, inner, ops):
        super().__init__(inner, ops)
        self._denied_once = False

    def write(self, offset, data):
        if not self._denied_once:
            self._denied_once = True
            raise OSError(5, "Access is denied (simulated scrub denial)")
        return super().write(offset, data)


def _make_job(tmp_path, fake_platform_io, monkeypatch, payload):
    img = tmp_path / "m.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(2, size=len(payload) + 8192)
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY], imager_version="0.2.0",
        flashed_at_iso="2026-06-12T03:00:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"),
    )
    monkeypatch.setattr(
        "astromechos_imager.core.orchestrator._bootpartition_open",
        lambda *a, **kw: None)
    return FlashJob(
        platform_io=fake_platform_io, image_path=img,
        target=fake_platform_io.enumerate_removable_drives()[0],
        role=Role.MASTER, firstboot_config=cfg, master_pair=generate_ed25519(),
        skip_verify=True, skip_customize=True,
    )


def test_scrub_is_first_write_then_deferred_mbr_restores_content(
        tmp_path, fake_platform_io, monkeypatch):
    payload = _mbr(b"R2" * 250_000)
    job = _make_job(tmp_path, fake_platform_io, monkeypatch, payload)

    ops: list[tuple[int, int, bool]] = []
    real_open = fake_platform_io.open_raw_device
    monkeypatch.setattr(
        fake_platform_io, "open_raw_device",
        lambda pid: _RecordingDevice(real_open(pid), ops))

    result = job.run()
    assert result.ok, f"flash failed: {result!r}"

    assert ops, "no writes recorded — recorder not wired"
    first_offset, first_len, first_all_zero = ops[0]
    assert first_offset == 0, (
        f"first device write must be the MBR scrub at offset 0, "
        f"got offset {first_offset}")
    assert first_all_zero, "the scrub write must be all zeros"
    assert first_len >= 4096, (
        f"scrub must cover at least 4096 bytes (one 4Kn sector), "
        f"got {first_len}")

    last_offset, _last_len, last_all_zero = ops[-1]
    assert last_offset == 0 and not last_all_zero, (
        "the deferred-MBR write (real image bytes at offset 0) must come "
        "LAST so the partition table appears on disk only after customize")

    dev = real_open(2)
    try:
        assert dev.read(0, len(payload)) == payload, (
            "final card content must be byte-identical to the source image "
            "— the deferred MBR must fully overwrite the scrubbed region")
    finally:
        dev.close()


def test_scrub_denial_is_non_fatal(tmp_path, fake_platform_io, monkeypatch):
    payload = _mbr(b"D2" * 250_000)
    job = _make_job(tmp_path, fake_platform_io, monkeypatch, payload)

    ops: list[tuple[int, int, bool]] = []
    real_open = fake_platform_io.open_raw_device
    monkeypatch.setattr(
        fake_platform_io, "open_raw_device",
        lambda pid: _ScrubDeniedDevice(real_open(pid), ops))

    result = job.run()
    assert result.ok, "a denied scrub must degrade gracefully, not abort"

    dev = real_open(2)
    try:
        assert dev.read(0, len(payload)) == payload
    finally:
        dev.close()


def test_scrub_clamps_to_tiny_devices(tmp_path, fake_platform_io, monkeypatch):
    """A device smaller than 4096 bytes (degenerate test rigs) must get a
    sector-multiple scrub no larger than the device, never an over-run."""
    payload = _mbr(b"X" * 600)          # 1024-byte image, 1024+8192 device
    job = _make_job(tmp_path, fake_platform_io, monkeypatch, payload)

    # Shrink the registered drive AND the sparse file to 2048 bytes.
    import os
    drive = fake_platform_io.drives[2]
    fake_platform_io.drives[2] = type(drive)(
        physical_drive_id=drive.physical_drive_id,
        device_path=drive.device_path,
        drive_letters=drive.drive_letters,
        size_bytes=2048,
        model=drive.model,
        serial=drive.serial,
    )
    os.truncate(tmp_path / "sparse_2.img", 2048)
    job.target = fake_platform_io.enumerate_removable_drives()[0]

    ops: list[tuple[int, int, bool]] = []
    real_open = fake_platform_io.open_raw_device
    monkeypatch.setattr(
        fake_platform_io, "open_raw_device",
        lambda pid: _RecordingDevice(real_open(pid), ops))

    result = job.run()
    assert result.ok
    first_offset, first_len, first_all_zero = ops[0]
    assert first_offset == 0 and first_all_zero
    assert first_len <= 2048 and first_len % 512 == 0
