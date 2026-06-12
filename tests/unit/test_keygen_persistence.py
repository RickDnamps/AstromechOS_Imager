# tests/unit/test_keygen_persistence.py
from astromechos_imager.core.keygen import (
    generate_ed25519,
    generate_hotspot_bootstrap,
    load_persisted_hotspot,
    load_persisted_pair,
    persisted_pair_dir,
    save_persisted_hotspot,
    save_persisted_pair,
)


def test_load_returns_none_when_absent(tmp_appdata):
    assert load_persisted_pair() is None
    assert load_persisted_hotspot() is None


def test_pair_roundtrip(tmp_appdata):
    original = generate_ed25519()
    save_persisted_pair(original)
    loaded = load_persisted_pair()
    assert loaded is not None
    assert loaded.private_openssh == original.private_openssh
    assert loaded.public_openssh == original.public_openssh


def test_hotspot_roundtrip(tmp_appdata):
    original = generate_hotspot_bootstrap("test-psk-12345")
    save_persisted_hotspot(original)
    loaded = load_persisted_hotspot()
    assert loaded is not None
    assert loaded.ssid == original.ssid
    assert loaded.password == original.password


def test_persisted_pair_dir_under_appdata(tmp_appdata):
    d = persisted_pair_dir()
    assert d.is_relative_to(tmp_appdata)
    assert d.name == "last_pair"
