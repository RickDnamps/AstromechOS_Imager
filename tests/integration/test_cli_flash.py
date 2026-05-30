# tests/integration/test_cli_flash.py
import pytest
from pathlib import Path
from astromechos_imager.cli.main import _cmd_flash, build_parser

pytestmark = pytest.mark.integration


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_cli_flash_pair(tmp_path, fake_platform_io, monkeypatch):
    payload = _mbr(b"X" * 200_000)
    m = tmp_path / "master.img"; m.write_bytes(payload)
    s = tmp_path / "slave.img"; s.write_bytes(payload)
    keys = tmp_path / "id.pub"; keys.write_text(VALID_KEY + "\n")
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    fake_platform_io.add_drive(3, size=len(payload) + 1024)
    monkeypatch.setattr("astromechos_imager.core.orchestrator._bootpartition_open",
                         lambda *a, **kw: None)
    monkeypatch.setattr("astromechos_imager.cli.main._build_platform_io",
                         lambda: fake_platform_io)
    args = build_parser().parse_args([
        "flash", "--master-image", str(m), "--master-drive", "2",
        "--slave-image", str(s), "--slave-drive", "3",
        "--keys-file", str(keys), "--no-verify",
        "--hotspot-psk", "test-hotspot-psk",
    ])
    rc = _cmd_flash(args)
    assert rc == 0
