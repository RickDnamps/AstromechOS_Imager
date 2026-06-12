# tests/integration/test_pair_flash.py
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig
from astromechos_imager.core.orchestrator import PairFlashJob, PairFlashResult

VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_parallel_pair_flash(tmp_path, fake_platform_io, monkeypatch):
    payload_m = _mbr(b"M" * 500_000)
    payload_s = _mbr(b"S" * 400_000)
    p_m = tmp_path / "master.img"; p_m.write_bytes(payload_m)
    p_s = tmp_path / "slave.img"; p_s.write_bytes(payload_s)
    fake_platform_io.add_drive(2, size=len(payload_m) + 1024)
    fake_platform_io.add_drive(3, size=len(payload_s) + 1024)
    monkeypatch.setattr("astromechos_imager.core.orchestrator._bootpartition_open",
                         lambda *a, **kw: None)

    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY], imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"),
    )
    drives = {d.physical_drive_id: d for d in fake_platform_io.enumerate_removable_drives()}
    job = PairFlashJob(
        platform_io=fake_platform_io,
        master_image=p_m, master_target=drives[2],
        slave_image=p_s, slave_target=drives[3],
        firstboot_config=cfg,
        master_pair=generate_ed25519(),
        parallel=True,
        skip_verify=True, skip_customize=True,
    )
    res = job.run()
    assert isinstance(res, PairFlashResult)
    assert res.master.ok and res.slave.ok


def test_sequential_pair_flash(tmp_path, fake_platform_io, monkeypatch):
    payload = _mbr(b"X" * 200_000)
    p = tmp_path / "im.img"; p.write_bytes(payload)
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    fake_platform_io.add_drive(3, size=len(payload) + 1024)
    monkeypatch.setattr("astromechos_imager.core.orchestrator._bootpartition_open",
                         lambda *a, **kw: None)
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY], imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"),
    )
    drives = {d.physical_drive_id: d for d in fake_platform_io.enumerate_removable_drives()}
    job = PairFlashJob(
        platform_io=fake_platform_io,
        master_image=p, master_target=drives[2],
        slave_image=p, slave_target=drives[3],
        firstboot_config=cfg, master_pair=generate_ed25519(),
        parallel=False, skip_verify=True, skip_customize=True,
    )
    res = job.run()
    assert res.master.ok and res.slave.ok
