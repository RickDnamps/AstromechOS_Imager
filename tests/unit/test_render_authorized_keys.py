# tests/unit/test_render_authorized_keys.py
from astromechos_imager.core.customization import render_authorized_keys
from astromechos_imager.core.models import FirstbootConfig, Role

USER_KEY = "ssh-ed25519 AAAAUUUUSER user@laptop"
MASTER_PUB = b"ssh-ed25519 AAAAMMMMASTER astromech-master@imager\n"


def _cfg(keys=None):
    return FirstbootConfig(
        authorized_keys=keys or [USER_KEY],
        imager_version="0.1.0", flashed_at_iso="2026-05-29T02:15:00Z",
    )


def test_master_authorized_keys_is_just_user_keys():
    out = render_authorized_keys(_cfg(), Role.MASTER, master_pub=MASTER_PUB).decode("utf-8")
    assert out.strip().splitlines() == [USER_KEY]


def test_slave_inherits_master_pub():
    out = render_authorized_keys(_cfg(), Role.SLAVE, master_pub=MASTER_PUB).decode("utf-8")
    lines = out.strip().splitlines()
    assert USER_KEY in lines
    assert "ssh-ed25519 AAAAMMMMASTER astromech-master@imager" in lines


def test_trailing_newline_for_awk_NF():
    """firstboot_setup.sh:133 uses awk 'NF' which requires a final newline."""
    out = render_authorized_keys(_cfg(), Role.MASTER, master_pub=MASTER_PUB)
    assert out.endswith(b"\n")


def test_keys_stripped():
    out = render_authorized_keys(_cfg(keys=[f"  {USER_KEY}  "]), Role.MASTER, master_pub=MASTER_PUB)
    assert b"  " not in out.replace(b" user@", b"")  # no leading spaces remain
