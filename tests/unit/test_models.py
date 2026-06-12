# tests/unit/test_models.py
import pytest

from astromechos_imager.core.models import Ed25519Pair, HotspotBootstrap, Role


def test_role_values():
    assert Role.MASTER.value == "master"
    assert Role.SLAVE.value == "slave"


def test_hotspot_bootstrap_is_frozen():
    b = HotspotBootstrap(ssid="Astromech-3742", password="x" * 32)
    with pytest.raises(AttributeError):  # dataclass(frozen=True)
        b.ssid = "other"  # type: ignore[misc]


def test_ed25519_pair_carries_bytes():
    p = Ed25519Pair(private_openssh=b"PRIV", public_openssh=b"ssh-ed25519 KEY\n")
    assert p.private_openssh == b"PRIV"
    assert p.public_openssh.endswith(b"\n")
