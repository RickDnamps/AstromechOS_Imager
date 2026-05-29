# tests/unit/test_render_init_config_json.py
import json
from astromechos_imager.core.customization import render_init_config_json
from astromechos_imager.core.models import FirstbootConfig, Role


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY user@host"


def _cfg(**kw):
    base = dict(authorized_keys=[VALID_KEY], imager_version="0.1.0",
                flashed_at_iso="2026-05-29T02:15:00Z")
    base.update(kw)
    return FirstbootConfig(**base)


def test_master_payload():
    out = render_init_config_json(_cfg(), Role.MASTER)
    obj = json.loads(out)
    assert obj == {
        "role": "master",
        "hostname": "astromech-master",
        "imager_version": "0.1.0",
        "flashed_at": "2026-05-29T02:15:00Z",
    }


def test_slave_payload():
    out = render_init_config_json(_cfg(), Role.SLAVE)
    obj = json.loads(out)
    assert obj["role"] == "slave"
    assert obj["hostname"] == "astromech-slave"


def test_hostname_override():
    cfg = _cfg(hostname_master="r2-dome")
    obj = json.loads(render_init_config_json(cfg, Role.MASTER))
    assert obj["hostname"] == "r2-dome"


def test_trailing_newline():
    out = render_init_config_json(_cfg(), Role.MASTER)
    assert out.endswith(b"\n")
