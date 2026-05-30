# tests/integration/test_flashjob.py
import lzma
import pytest
from pathlib import Path
from astromechos_imager.core.orchestrator import FlashJob, FlashJobResult
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role

pytestmark = pytest.mark.integration


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_flash_job_master_end_to_end(tmp_path, fake_platform_io, monkeypatch):
    # Skip the customize step (no real FAT32 in fake_platform_io test path)
    payload = _mbr(b"R2" * 250_000)
    img = tmp_path / "master.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        imager_version="0.1.0", flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"),
    )
    pair = generate_ed25519()
    # Stub the boot-partition open so we don't need a real FAT32 layout in fake SD
    monkeypatch.setattr("astromechos_imager.core.orchestrator._bootpartition_open",
                        lambda *a, **kw: None)

    job = FlashJob(
        platform_io=fake_platform_io,
        image_path=img,
        target=fake_platform_io.enumerate_removable_drives()[0],
        role=Role.MASTER,
        firstboot_config=cfg,
        master_pair=pair,
        skip_verify=True,
        skip_customize=True,
    )
    result = job.run()
    assert isinstance(result, FlashJobResult)
    assert result.ok
