"""Cryptographic + bootstrap-credential generators. Per design spec §6.2."""
from __future__ import annotations

import secrets

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from astromechos_imager.core.models import Ed25519Pair, HotspotBootstrap


def generate_ed25519(comment: str = "astromech-master@imager") -> Ed25519Pair:
    """Generate a fresh ed25519 keypair in OpenSSH wire format.

    The public half carries the comment as the third whitespace-separated field
    (same convention as `ssh-keygen`). firstboot_setup.sh:147-158 copies the file
    verbatim into ~/.ssh/, so the comment survives to the Pi.
    """
    sk = Ed25519PrivateKey.generate()
    priv = sk.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.OpenSSH,
        encryption_algorithm=NoEncryption(),
    )
    pub = sk.public_key().public_bytes(
        encoding=Encoding.OpenSSH,
        format=PublicFormat.OpenSSH,
    )
    pub_with_comment = pub + b" " + comment.encode("ascii") + b"\n"
    return Ed25519Pair(private_openssh=priv, public_openssh=pub_with_comment)
