"""Cryptographic + bootstrap-credential generators. Per design spec §6.2."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import string
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from astromechos_imager.core.models import Ed25519Pair, HotspotBootstrap, LinuxAccount


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


# ── wlan0 bootstrap rendezvous (random SSID per burn, operator PSK) ───
#
# Per CLAUDE.md dual-WLAN invariant: the Imager generates a fresh
# ``Astromech-<4 decimal digits>`` SSID PER BURN and writes the same
# SSID + the operator-supplied PSK into ``[hotspot]`` of
# ``/boot/astromech_init.cfg`` on BOTH cards of a pair. The random
# 4-digit suffix prevents collision when multiple unboxed pairs are
# powered up in the same workshop — each pair finds itself before
# ``firstboot_setup.sh`` invokes ``gen_hotspot_ssid.sh`` to derive
# the FINAL per-robot ``Astromech_Control_<XXXX>`` SSID from the
# Master's CPU serial. The Master then pushes the rotated creds to
# the Slave over SSH and persists them in ``local.cfg`` — the Imager
# never sees the FINAL SSID.
#
# Why the operator picks the PSK:
#   * The bootstrap window is narrow (≤5 min before handover) but the
#     PSK CARRIES THROUGH the handover by default
#     (``FINAL_PSK="$BOOT_PSK"`` — see firstboot_setup.sh:433). A
#     fixed/known-public PSK would let a workshop neighbour camp the
#     final per-robot AP. Operator-supplied keeps the secret out of
#     git history.
def generate_hotspot_ssid() -> str:
    """Return a fresh random bootstrap SSID ``Astromech-<4 decimal digits>``.

    Collision-free per burn (4×10⁴ values) so simultaneously-unboxed pairs in
    the same workshop don't camp the same wlan0 rendezvous. The SSID is
    independent of the hotspot PSK — the UI mints it ONCE at wizard-state init
    (``wizardState.hotspotSsid``) and the same value is baked into BOTH cards
    of a pair; ``firstboot_setup.sh`` later rotates to the final
    serial-derived ``Astromech_Control_<XXXX>`` SSID. Matches
    ``core.validators._SSID_RE`` (``^Astromech-[0-9]{4}$``).
    """
    return f"Astromech-{secrets.randbelow(10000):04d}"


def generate_hotspot_bootstrap(password: str) -> HotspotBootstrap:
    """Return a fresh bootstrap rendezvous with random SSID + operator PSK.

    Dual-WLAN architecture (per CLAUDE.md):
      * ``wlan0`` — onboard radio, private Master↔Slave AP. The
        Imager generates a fresh ``Astromech-<4 digits>`` SSID per
        burn (4×10⁴ possible values, suitable for a workshop with
        dozens of simultaneous pair-burns) and writes the IDENTICAL
        SSID + ``password`` into ``[hotspot]`` of
        ``/boot/astromech_init.cfg`` on BOTH cards of the pair via
        ``FirstbootConfig.hotspot_bootstrap``. The live
        ``firstboot_setup.sh`` reads these verbatim, brings the AP
        up, then ``gen_hotspot_ssid.sh`` rotates to the FINAL
        serial-derived SSID and the Master pushes the new creds to
        the Slave over SSH.
      * ``wlan1`` — USB dongle, gets the operator-supplied
        domestic-network credentials from a different code path
        (``FirstbootConfig.wifi_ssid`` / ``wifi_psk`` →
        ``render_wlan_conf`` in ``core/customization.py``, written
        as ``/boot/astromech_wlan.conf``).

    Validation lives in ``core/validators.validate_wpa2_psk``: 8-63
    ASCII printable characters, IEEE 802.11i. This function refuses
    obvious garbage to keep the contract honest; the caller (UI
    keystroke validator + ``FirstbootConfig.__post_init__``) is the
    enforcement boundary.
    """
    if not password or len(password) < 8:
        raise ValueError(
            "hotspot bootstrap PSK must be ≥8 characters (WPA2-PSK minimum)"
        )
    return HotspotBootstrap(
        ssid=generate_hotspot_ssid(),
        password=password,
    )


# ── Linux account (Cold rootfs surgery target — Phase 5.5) ────────────────


# SHA512-CRYPT salt alphabet per Drepper's spec — 64-char set used by
# glibc's crypt(3) implementation. 16 chars is the maximum the algorithm
# accepts; longer salts are silently truncated.
_SHA512_CRYPT_SALT_ALPHABET = string.ascii_letters + string.digits + "./"


def _sha512_crypt(password: str, salt: str | None = None,
                  rounds: int = 5000) -> str:
    """Pure-Python SHA512-CRYPT compatible with glibc ``crypt(3)``.

    Produces a ``$6$<salt>$<hash>`` string that the Imager passes to the
    first-boot ``firstrun.sh`` (``chpasswd -e`` / ``userconf``). Reference
    implementation: Ulrich Drepper, https://akkadia.org/drepper/SHA-crypt.txt.

    Pure Python (not stdlib ``crypt`` — that module is Unix-only and
    deprecated in Python 3.13; the Imager runs on Windows where it is
    unavailable). 5000 rounds matches the glibc default and what
    ``passwd`` writes by default.
    """
    if salt is None:
        salt = "".join(
            secrets.choice(_SHA512_CRYPT_SALT_ALPHABET) for _ in range(16)
        )
    if len(salt) > 16:
        salt = salt[:16]

    pwd = password.encode("utf-8")
    salt_b = salt.encode("ascii")

    # Step 1-3
    a = hashlib.sha512()
    a.update(pwd)
    a.update(salt_b)

    # Step 4-8
    b = hashlib.sha512()
    b.update(pwd)
    b.update(salt_b)
    b.update(pwd)
    b_digest = b.digest()

    # Step 9-10
    cnt = len(pwd)
    while cnt > 64:
        a.update(b_digest)
        cnt -= 64
    a.update(b_digest[:cnt])

    # Step 11
    cnt = len(pwd)
    while cnt > 0:
        if cnt & 1:
            a.update(b_digest)
        else:
            a.update(pwd)
        cnt >>= 1
    a_digest = a.digest()

    # Step 13-15 — DP
    dp = hashlib.sha512()
    for _ in range(len(pwd)):
        dp.update(pwd)
    dp_digest = dp.digest()
    P = b""
    cnt = len(pwd)
    while cnt >= 64:
        P += dp_digest
        cnt -= 64
    P += dp_digest[:cnt]

    # Step 16-19 — DS
    ds = hashlib.sha512()
    for _ in range(16 + a_digest[0]):
        ds.update(salt_b)
    ds_digest = ds.digest()
    S = b""
    cnt = len(salt_b)
    while cnt >= 64:
        S += ds_digest
        cnt -= 64
    S += ds_digest[:cnt]

    # Step 21 — main loop
    C = a_digest
    for i in range(rounds):
        c = hashlib.sha512()
        c.update(P if (i & 1) else C)
        if i % 3:
            c.update(S)
        if i % 7:
            c.update(P)
        c.update(C if (i & 1) else P)
        C = c.digest()

    # Step 22 — base64 (modified alphabet, specific byte permutation)
    _B64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

    def _b64_encode(b1: int, b2: int, b3: int, n: int) -> str:
        v = (b1 << 16) | (b2 << 8) | b3
        out = []
        for _ in range(n):
            out.append(_B64[v & 0x3F])
            v >>= 6
        return "".join(out)

    order = [
        (0, 21, 42, 4),  (22, 43, 1, 4),  (44, 2, 23, 4),  (3, 24, 45, 4),
        (25, 46, 5, 4),  (47, 6, 26, 4),  (7, 27, 48, 4),  (28, 49, 8, 4),
        (50, 9, 29, 4),  (10, 30, 51, 4), (31, 52, 11, 4), (53, 12, 32, 4),
        (13, 33, 54, 4), (34, 55, 14, 4), (56, 15, 35, 4), (16, 36, 57, 4),
        (37, 58, 17, 4), (59, 18, 38, 4), (19, 39, 60, 4), (40, 61, 20, 4),
        (62, 63, 0, 2),  # last block: only 2 chars from b63 high bits
    ]
    encoded_parts = []
    for b1, b2, b3, n in order[:-1]:
        encoded_parts.append(_b64_encode(C[b1], C[b2], C[b3], n))
    # Final 2-char block uses C[63] only (b1 set to C[63], b2/b3 = 0).
    encoded_parts.append(_b64_encode(0, 0, C[63], 2))
    encoded = "".join(encoded_parts)

    # Step 23
    prefix = "$6$"
    if rounds != 5000:
        prefix += f"rounds={rounds}$"
    return f"{prefix}{salt}${encoded}"


def generate_linux_account(username: str, cleartext_password: str) -> LinuxAccount:
    """Build the ``LinuxAccount`` used for first-boot account setup.

    The Imager writes ``username`` + the SHA512-CRYPT hash of
    ``cleartext_password`` into ``/firstrun.sh`` so the Pi renames UID-1000
    and sets its password on first boot.

    Validation is the *caller's* responsibility (the UI wires its
    on-keystroke validators to ``core/validators.validate_install_user``
    and a password-strength check); this function trusts its inputs and
    refuses obvious garbage to keep the contract honest.
    """
    if not username:
        raise ValueError("username must be non-empty")
    if not cleartext_password:
        raise ValueError("cleartext_password must be non-empty")
    return LinuxAccount(
        username=username,
        cleartext_password=cleartext_password,
        crypt_sha512=_sha512_crypt(cleartext_password),
    )


# ── Persistence ───────────────────────────────────────────────────────────────


def _appdata_root() -> Path:
    """%APPDATA%\\AstromechOS Imager  — env-overridable for tests."""
    base = os.environ.get("APPDATA")
    if not base:
        raise RuntimeError("APPDATA env var not set (Windows-only path)")
    return Path(base) / "AstromechOS Imager"


def persisted_pair_dir() -> Path:
    d = _appdata_root() / "last_pair"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_persisted_pair(pair: Ed25519Pair) -> None:
    d = persisted_pair_dir()
    (d / "id_ed25519").write_bytes(pair.private_openssh)
    (d / "id_ed25519.pub").write_bytes(pair.public_openssh)


def load_persisted_pair() -> Ed25519Pair | None:
    """Reload the previously-persisted Master↔Slave keypair.

    Audit Medium #29: previously a partial / truncated / hand-edited
    keypair was wrapped into ``Ed25519Pair`` and flashed onto a card
    whose first-boot SSH would then irreversibly fail. Now both files
    are minimally validated before we trust them. On any inconsistency
    we return ``None`` so the caller regenerates + re-persists a fresh
    pair (and the existing Slave's authorized_keys will need updating
    on its next flash, but that's the operator's signal that something
    is wrong rather than a silent broken handshake).
    """
    d = persisted_pair_dir()
    priv_p = d / "id_ed25519"
    pub_p = d / "id_ed25519.pub"
    if not (priv_p.is_file() and pub_p.is_file()):
        return None
    try:
        priv = priv_p.read_bytes()
        pub = pub_p.read_bytes()
    except OSError:
        return None
    # PEM header check — generate_ed25519 always writes
    # "-----BEGIN OPENSSH PRIVATE KEY-----" as the first line.
    if not priv.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----"):
        return None
    # OpenSSH pub key format: "ssh-ed25519 <base64> [comment]\n".
    pub_text = pub.decode("ascii", errors="replace").strip()
    if not pub_text.startswith("ssh-ed25519 "):
        return None
    parts = pub_text.split(maxsplit=2)
    if len(parts) < 2:
        return None
    return Ed25519Pair(private_openssh=priv, public_openssh=pub)


def save_persisted_hotspot(b: HotspotBootstrap) -> None:
    d = persisted_pair_dir()
    (d / "hotspot.json").write_text(
        json.dumps({"ssid": b.ssid, "password": b.password}), encoding="utf-8"
    )


def load_persisted_hotspot() -> HotspotBootstrap | None:
    p = persisted_pair_dir() / "hotspot.json"
    if not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    return HotspotBootstrap(ssid=obj["ssid"], password=obj["password"])
