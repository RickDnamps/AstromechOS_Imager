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
from astromechos_imager.core.models import Role

_STALE_NM_RM = (
    "rm -f /etc/NetworkManager/system-connections/astromech-master-hotspot.nmconnection"
)
_MASTER_HOTSPOT_RM = (
    "rm -f /etc/NetworkManager/system-connections/astromech-hotspot.nmconnection"
)
_MASTER_INTERNET_RM = (
    "rm -f /etc/NetworkManager/system-connections/astromech-internet.nmconnection"
)
_MASTER_R2D2_INTERNET_RM = (
    "rm -f /etc/NetworkManager/system-connections/r2d2-internet.nmconnection"
)
_SLAVE_R2D2_MASTER_HOTSPOT_RM = (
    "rm -f /etc/NetworkManager/system-connections/r2d2-master-hotspot.nmconnection"
)
_NMCLI_RELOAD = "nmcli connection reload"

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


# ── runcmd (slave-only NM profile cleanup, 2026-06-04) ──────────────────────
def test_user_data_slave_includes_runcmd_for_stale_nm_profile():
    """Slave user-data must run cleanup runcmd at first boot to remove the
    stale astromech-master-hotspot.nmconnection inherited from the Golden
    Image — it has autoconnect-priority=100 which would otherwise outrank
    our netplan-generated profile pointing at the real hotspot SSID."""
    out = generate_user_data("astromech", HASH, role=Role.SLAVE).decode("utf-8")
    assert "runcmd:" in out
    assert _STALE_NM_RM in out


def test_user_data_master_omits_runcmd():
    """Master user-data MUST NOT include the cleanup runcmd — the legacy
    master needs that NM profile to remain working in production."""
    out = generate_user_data("astromech", HASH, role=Role.MASTER).decode("utf-8")
    # Either no runcmd block at all, or runcmd does NOT contain the rm
    assert _STALE_NM_RM not in out


def test_user_data_default_role_is_master_and_omits_runcmd():
    """Backwards compat: callers that haven't been updated to pass ``role``
    must keep producing the unchanged master shape (no runcmd)."""
    out = generate_user_data("astromech", HASH).decode("utf-8")
    assert _STALE_NM_RM not in out


def test_user_data_runcmd_is_proper_yaml_list():
    """The runcmd block must parse as valid YAML (list of strings)."""
    yaml = pytest.importorskip("yaml")
    out = generate_user_data("astromech", HASH, role=Role.SLAVE)
    parsed = yaml.safe_load(out)
    assert isinstance(parsed, dict)
    assert "runcmd" in parsed
    assert isinstance(parsed["runcmd"], list)
    assert len(parsed["runcmd"]) >= 1
    assert all(isinstance(cmd, str) for cmd in parsed["runcmd"])
    # And it must contain exactly the targeted scrub command
    assert any(_STALE_NM_RM in cmd for cmd in parsed["runcmd"])


# ── role-aware runcmd scrub (2026-06-05) ────────────────────────────────────
def test_master_runcmd_wipes_authorized_keys():
    """Master must rm the stale ~/.ssh/authorized_keys at first boot so the
    previous master's pubkey cannot reach this card. Path uses the supplied
    username (NEVER hardcoded astromech)."""
    out = generate_user_data("astromech", HASH, role=Role.MASTER).decode("utf-8")
    assert "runcmd:" in out
    assert "rm -f /home/astromech/.ssh/authorized_keys" in out


def test_master_runcmd_wipes_wlan0_and_wlan1_profiles():
    """Master must rm both the wlan0 AP profile and the wlan1 client profile
    inherited from the Golden Image (legacy SSID/PSK + previous operator's
    home WiFi creds)."""
    out = generate_user_data("astromech", HASH, role=Role.MASTER).decode("utf-8")
    assert _MASTER_HOTSPOT_RM in out
    assert _MASTER_INTERNET_RM in out
    assert _MASTER_R2D2_INTERNET_RM in out


def test_master_runcmd_does_not_wipe_slave_profiles():
    """Master must NOT touch the slave's stale astromech-master-hotspot
    profile (which lives only on slave cards anyway)."""
    out = generate_user_data("astromech", HASH, role=Role.MASTER).decode("utf-8")
    assert _STALE_NM_RM not in out
    assert _SLAVE_R2D2_MASTER_HOTSPOT_RM not in out


def test_slave_runcmd_wipes_authorized_keys_and_master_hotspot():
    """Slave must rm the stale authorized_keys AND the legacy master-hotspot
    NM profile baked into the Golden."""
    out = generate_user_data("astromech", HASH, role=Role.SLAVE).decode("utf-8")
    assert "rm -f /home/astromech/.ssh/authorized_keys" in out
    assert _STALE_NM_RM in out
    assert _SLAVE_R2D2_MASTER_HOTSPOT_RM in out


def test_slave_runcmd_does_not_wipe_master_only_profiles():
    """Slave must NOT touch the master-only wlan0 AP / wlan1 client profiles
    — those don't exist on slave cards."""
    out = generate_user_data("astromech", HASH, role=Role.SLAVE).decode("utf-8")
    assert _MASTER_HOTSPOT_RM not in out
    assert _MASTER_INTERNET_RM not in out
    assert _MASTER_R2D2_INTERNET_RM not in out


def test_both_runcmd_ends_with_nmcli_reload():
    """The LAST runcmd line for each role must be `nmcli connection reload`
    so NetworkManager drops in-memory profiles whose backing files just
    disappeared. Exactly one reload per role (never more)."""
    yaml = pytest.importorskip("yaml")
    for role in (Role.MASTER, Role.SLAVE):
        out = generate_user_data("astromech", HASH, role=role)
        parsed = yaml.safe_load(out)
        assert parsed["runcmd"][-1] == _NMCLI_RELOAD, role
        # Exactly one reload per role — defensive against accidental dupes.
        assert sum(1 for c in parsed["runcmd"] if c == _NMCLI_RELOAD) == 1


def test_username_is_not_hardcoded():
    """The authorized_keys scrub path must interpolate the supplied username
    (HARD RULE: code is 100% username-agnostic — see CLAUDE.md). A custom
    username MUST appear in the path and `astromech` MUST NOT."""
    out = generate_user_data("custom_user", HASH, role=Role.MASTER).decode("utf-8")
    assert "rm -f /home/custom_user/.ssh/authorized_keys" in out
    assert "/home/astromech/" not in out
    # And again on slave for symmetry.
    out_s = generate_user_data("custom_user", HASH, role=Role.SLAVE).decode("utf-8")
    assert "rm -f /home/custom_user/.ssh/authorized_keys" in out_s
    assert "/home/astromech/" not in out_s


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
