"""Unit tests for the cloud-init NoCloud seed + cmdline generator."""
from __future__ import annotations

import re

import pytest

from astromechos_imager.core.cloud_init_generator import (
    RESIZE_TOKEN,
    build_cmdline,
    generate_instance_id,
    generate_meta_data,
    generate_user_data,
)

HASH = "$6$abcd1234efgh5678$" + "Z" * 86  # plausible $6$ SHA-512 crypt shape


def _count(cmdline: bytes, predicate) -> int:
    return sum(1 for t in cmdline.decode("ascii").split() if predicate(t))


# ── instance-id ────────────────────────────────────────────────────────────
def test_instance_id_official_format():
    assert generate_instance_id(1780381847245) == "rpi-imager-1780381847245"
    # matches the format observed on a real official rpi-imager Trixie card
    assert re.fullmatch(r"rpi-imager-\d+", generate_instance_id(1))


# ── meta-data ────────────────────────────────────────────────────────────────
def test_meta_data_is_only_instance_id():
    md = generate_meta_data("rpi-imager-42").decode("ascii")
    assert md.strip() == "instance-id: rpi-imager-42"
    # hostname is owned by the AstromechOS firstboot — must NOT appear here
    assert "hostname" not in md


# ── user-data ────────────────────────────────────────────────────────────────
def test_user_data_reconfigures_existing_user_creates_nothing():
    ud = generate_user_data("artoo", HASH).decode("utf-8")
    assert ud.startswith("#cloud-config")
    # RECONFIGURE, never create: empty users list suppresses all account creation
    assert "users: []" in ud
    assert "name: 'artoo'" in ud
    assert "chpasswd:" in ud and "type: hash" in ud
    assert f"password: '{HASH}'" in ud
    assert "ssh_pwauth: true" in ud
    # must NOT define a new account (no groups/shell create block)
    assert "groups:" not in ud
    assert "shell:" not in ud
    # cloud-init owns ONLY the password here; these stay with firstboot
    assert "hostname" not in ud
    assert "wifi" not in ud.lower() and "ssid" not in ud.lower()


def test_user_data_is_valid_yaml_cloud_config():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(generate_user_data("artoo", HASH))
    # empty users list => cloud-init creates no account (not even the default)
    assert doc["users"] == []
    cp = doc["chpasswd"]
    assert cp["expire"] is False
    assert cp["users"][0] == {"name": "artoo", "password": HASH, "type": "hash"}
    assert doc["ssh_pwauth"] is True


def test_user_data_yaml_escapes_single_quote_in_username():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(generate_user_data("o'brien", HASH))
    assert doc["chpasswd"]["users"][0]["name"] == "o'brien"


# ── cmdline ──────────────────────────────────────────────────────────────────
BARE_GOLDEN = (
    b"console=serial0,115200 console=tty1 root=PARTUUID=d89b055c-02 "
    b"rootfstype=ext4 fsck.repair=yes rootwait cfg80211.ieee80211_regdom=CA\n"
)


def test_bare_golden_gets_resize_and_ds_nocloud():
    out = build_cmdline(BARE_GOLDEN, "rpi-imager-99")
    toks = out.decode("ascii").split()
    assert toks.count(RESIZE_TOKEN) == 1
    assert "ds=nocloud;i=rpi-imager-99" in toks
    assert b"\n" == out[-1:]
    # original args preserved
    assert "root=PARTUUID=d89b055c-02" in toks
    assert "cfg80211.ieee80211_regdom=CA" in toks
    # never the dead PID-1 hack
    assert not any(t.startswith("init=") for t in toks)


def test_strips_stale_init_and_firstrun_trigger():
    """A card flashed by the old tool (init= + systemd.run) is cleaned up."""
    stale = (
        b"console=tty1 root=PARTUUID=aa-02 rootwait "
        b"init=/usr/lib/raspberrypi-sys-mod/init_resize.sh "
        b"systemd.run=/boot/firstrun.sh systemd.run_success_action=reboot "
        b"systemd.unit=kernel-command-line.target\n"
    )
    toks = build_cmdline(stale, "rpi-imager-7").decode("ascii").split()
    assert not any(t.startswith("init=") for t in toks)
    assert not any(t.startswith("systemd.") for t in toks)
    assert toks.count(RESIZE_TOKEN) == 1
    assert "ds=nocloud;i=rpi-imager-7" in toks


def test_idempotent_no_duplicate_resize_or_ds():
    once = build_cmdline(BARE_GOLDEN, "rpi-imager-5")
    twice = build_cmdline(once, "rpi-imager-5")
    assert once == twice
    toks = twice.decode("ascii").split()
    assert toks.count(RESIZE_TOKEN) == 1
    assert _count(twice, lambda t: t.startswith("ds=nocloud")) == 1


def test_reflash_replaces_old_instance_id():
    first = build_cmdline(BARE_GOLDEN, "rpi-imager-1000")
    second = build_cmdline(first, "rpi-imager-2000")
    toks = second.decode("ascii").split()
    assert "ds=nocloud;i=rpi-imager-2000" in toks
    assert "ds=nocloud;i=rpi-imager-1000" not in toks
    assert _count(second, lambda t: t.startswith("ds=nocloud")) == 1
