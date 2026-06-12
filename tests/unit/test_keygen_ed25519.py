# tests/unit/test_keygen_ed25519.py
from cryptography.hazmat.primitives.serialization import load_ssh_private_key, load_ssh_public_key

from astromechos_imager.core.keygen import generate_ed25519
from astromechos_imager.core.models import Ed25519Pair


def test_generate_returns_pair():
    p = generate_ed25519()
    assert isinstance(p, Ed25519Pair)
    assert p.private_openssh.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----")
    assert p.public_openssh.startswith(b"ssh-ed25519 ")
    assert p.public_openssh.endswith(b"\n")


def test_public_includes_comment():
    p = generate_ed25519(comment="r2d2@imager")
    assert p.public_openssh.rstrip(b"\n").endswith(b" r2d2@imager")


def test_keys_are_parseable_by_cryptography():
    p = generate_ed25519()
    pub = load_ssh_public_key(p.public_openssh)
    sk = load_ssh_private_key(p.private_openssh, password=None)
    assert sk.public_key().public_bytes_raw() == pub.public_bytes_raw()


def test_two_calls_produce_different_keys():
    a, b = generate_ed25519(), generate_ed25519()
    assert a.private_openssh != b.private_openssh
