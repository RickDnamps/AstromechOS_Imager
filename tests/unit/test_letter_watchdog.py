# tests/unit/test_letter_watchdog.py
"""Mid-flash letter watchdog + sticky-binding purge (field log 2026-06-12 #2).

The 0.2.1 mbr-scrub was not enough: on REMOVABLE media a blank sector 0
still yields a whole-disk "superfloppy" RAW volume on re-enumeration, and
a sticky MountedDevices binding re-letters it — "Format this disk?"
popped 42 s into the master write. Two defenses are pinned here:

  1. ``purge_stale_mount_points`` (mountvol /R) is invoked once per flash,
     after the device is open (old volumes torn down → bindings stale);
  2. a watchdog thread polls ``letters_on_disk(target)`` for the whole
     device-open window and strips any letter that appears, and it is
     STOPPED before the cancel-path exFAT restore (whose diskpart
     "assign" must not be raced).
"""
import lzma
import time

from astromechos_imager.core import orchestrator
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


def _make_job(tmp_path, fake_platform_io, monkeypatch, payload=None):
    payload = payload if payload is not None else _mbr(b"R2" * 250_000)
    img = tmp_path / "m.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(2, size=len(payload) + 8192)
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY], imager_version="0.2.2",
        flashed_at_iso="2026-06-12T04:00:00Z",
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


def test_purge_stale_mount_points_called_once_per_flash(
        tmp_path, fake_platform_io, monkeypatch):
    calls = []
    fake_platform_io.purge_stale_mount_points = lambda: (calls.append(1), True)[1]
    job = _make_job(tmp_path, fake_platform_io, monkeypatch)
    assert job.run().ok
    assert calls == [1], "mountvol /R must run exactly once per flash"


def test_purge_failure_is_non_fatal(tmp_path, fake_platform_io, monkeypatch):
    fake_platform_io.purge_stale_mount_points = lambda: False
    job = _make_job(tmp_path, fake_platform_io, monkeypatch)
    assert job.run().ok, "a failed mountvol /R must not abort the flash"


def test_watchdog_strips_letter_that_appears_midflash(
        tmp_path, fake_platform_io, monkeypatch):
    monkeypatch.setattr(orchestrator, "_WATCHDOG_POLL_S", 0.005)

    state = {"lettered": True}
    stripped: list[str] = []

    fake_platform_io.letters_on_disk = (
        lambda pid: ["K"] if state["lettered"] else [])

    def fake_strip(letter):
        stripped.append(letter)
        state["lettered"] = False
        return True

    fake_platform_io.force_unmount_letter = fake_strip

    # Slow the device down a touch so the watchdog gets at least one tick
    # even on a fast CI box.
    real_open = fake_platform_io.open_raw_device

    class _SlowDev:
        def __init__(self, inner):
            self._inner = inner

        def write(self, offset, data):
            time.sleep(0.01)
            return self._inner.write(offset, data)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(
        fake_platform_io, "open_raw_device",
        lambda pid: _SlowDev(real_open(pid)))

    job = _make_job(tmp_path, fake_platform_io, monkeypatch)
    assert job.run().ok
    assert stripped and stripped[0] == "K", (
        "a letter appearing during the device-open window must be stripped "
        f"by the watchdog; stripped={stripped!r}")


def test_watchdog_stopped_before_cancel_restore(
        tmp_path, fake_platform_io, monkeypatch):
    """The cancel-path diskpart 'assign' must never be raced: after run()
    returns, the watchdog must be dead — no further strip calls even though
    the disk still reports a letter."""
    monkeypatch.setattr(orchestrator, "_WATCHDOG_POLL_S", 0.005)

    stripped: list[str] = []
    # Letterless until the device opens (so the pre-write active-wait gate
    # passes instantly), permanently lettered afterwards (so the watchdog
    # always has something to strip while it lives).
    state = {"opened": False}
    fake_platform_io.letters_on_disk = (
        lambda pid: ["K"] if state["opened"] else [])
    fake_platform_io.force_unmount_letter = (
        lambda letter: (stripped.append(letter), True)[1])
    restores: list[int] = []
    fake_platform_io.restore_readable_exfat = lambda pid: restores.append(pid)
    real_open = fake_platform_io.open_raw_device

    def opened(pid):
        state["opened"] = True
        return real_open(pid)

    monkeypatch.setattr(fake_platform_io, "open_raw_device", opened)

    job = _make_job(tmp_path, fake_platform_io, monkeypatch)
    job.cancel_event.set()
    job.run()

    assert restores == [2], "cancel path must restore the card"
    n_at_return = len(stripped)
    time.sleep(0.05)
    assert len(stripped) == n_at_return, (
        "watchdog must be joined before run() returns — it kept stripping "
        "after the flash ended (would race diskpart assign)")


def test_watchdog_absent_methods_degrade_silently(
        tmp_path, fake_platform_io, monkeypatch):
    """Platform fakes without letters_on_disk/force_unmount_letter (the
    minimal Protocol surface) must flash normally with no watchdog."""
    job = _make_job(tmp_path, fake_platform_io, monkeypatch)
    assert not hasattr(fake_platform_io, "letters_on_disk")
    assert job.run().ok
