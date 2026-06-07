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


# ── bootcmd (slave-only NM profile cleanup, 2026-06-04) ─────────────────────
def test_user_data_slave_includes_bootcmd_for_stale_nm_profile():
    """Slave user-data must run cleanup bootcmd at first boot to remove the
    stale astromech-master-hotspot.nmconnection inherited from the Golden
    Image — it has autoconnect-priority=100 which would otherwise outrank
    our netplan-generated profile pointing at the real hotspot SSID."""
    out = generate_user_data("astromech", HASH, role=Role.SLAVE).decode("utf-8")
    assert "bootcmd:" in out
    # Regression guard: must no longer use runcmd (race + cycle, 2026-06-06).
    assert "runcmd:" not in out
    assert _STALE_NM_RM in out


def test_user_data_master_omits_slave_nm_profile():
    """Master user-data MUST NOT include the slave's NM profile cleanup —
    the master role wipes different profiles than the slave."""
    out = generate_user_data("astromech", HASH, role=Role.MASTER).decode("utf-8")
    # The slave-specific rm must NOT appear in master output.
    assert _STALE_NM_RM not in out


def test_user_data_default_role_is_master_and_omits_slave_profiles():
    """Backwards compat: callers that haven't been updated to pass ``role``
    must default to master and not touch slave-side profiles."""
    out = generate_user_data("astromech", HASH).decode("utf-8")
    assert _STALE_NM_RM not in out


def test_user_data_bootcmd_is_proper_yaml_list():
    """The bootcmd block must parse as valid YAML (list of strings). Since
    2026-06-06 it is a single compound command guarded by a marker file (so
    it executes exactly once per Pi — see cc_bootcmd re-fire), so
    the list always has length 1."""
    yaml = pytest.importorskip("yaml")
    out = generate_user_data("astromech", HASH, role=Role.SLAVE)
    parsed = yaml.safe_load(out)
    assert isinstance(parsed, dict)
    assert "bootcmd" in parsed
    # Regression guard: must no longer emit runcmd.
    assert "runcmd" not in parsed
    assert isinstance(parsed["bootcmd"], list)
    assert len(parsed["bootcmd"]) == 1
    assert all(isinstance(cmd, str) for cmd in parsed["bootcmd"])
    # And it must contain exactly the targeted scrub command (embedded in
    # the compound shell guard).
    assert any(_STALE_NM_RM in cmd for cmd in parsed["bootcmd"])


# ── role-aware bootcmd scrub (2026-06-05) ───────────────────────────────────
def test_master_bootcmd_wipes_authorized_keys():
    """Master must rm the stale ~/.ssh/authorized_keys at first boot so the
    previous master's pubkey cannot reach this card. Path uses the supplied
    username (NEVER hardcoded astromech)."""
    out = generate_user_data("astromech", HASH, role=Role.MASTER).decode("utf-8")
    assert "bootcmd:" in out
    assert "runcmd:" not in out  # regression guard
    assert "rm -f /home/astromech/.ssh/authorized_keys" in out


def test_master_bootcmd_wipes_wlan0_and_wlan1_profiles():
    """Master must rm both the wlan0 AP profile and the wlan1 client profile
    inherited from the Golden Image (legacy SSID/PSK + previous operator's
    home WiFi creds)."""
    out = generate_user_data("astromech", HASH, role=Role.MASTER).decode("utf-8")
    assert _MASTER_HOTSPOT_RM in out
    assert _MASTER_INTERNET_RM in out
    assert _MASTER_R2D2_INTERNET_RM in out


def test_master_bootcmd_does_not_wipe_slave_profiles():
    """Master must NOT touch the slave's stale astromech-master-hotspot
    profile (which lives only on slave cards anyway)."""
    out = generate_user_data("astromech", HASH, role=Role.MASTER).decode("utf-8")
    assert _STALE_NM_RM not in out
    assert _SLAVE_R2D2_MASTER_HOTSPOT_RM not in out


def test_slave_bootcmd_wipes_authorized_keys_and_master_hotspot():
    """Slave must rm the stale authorized_keys AND the legacy master-hotspot
    NM profile baked into the Golden."""
    out = generate_user_data("astromech", HASH, role=Role.SLAVE).decode("utf-8")
    assert "rm -f /home/astromech/.ssh/authorized_keys" in out
    assert _STALE_NM_RM in out
    assert _SLAVE_R2D2_MASTER_HOTSPOT_RM in out


def test_slave_bootcmd_does_not_wipe_master_only_profiles():
    """Slave must NOT touch the master-only wlan0 AP / wlan1 client profiles
    — those don't exist on slave cards."""
    out = generate_user_data("astromech", HASH, role=Role.SLAVE).decode("utf-8")
    assert _MASTER_HOTSPOT_RM not in out
    assert _MASTER_INTERNET_RM not in out
    assert _MASTER_R2D2_INTERNET_RM not in out


def test_bootcmd_does_not_call_nmcli_reload():
    """At the ``cc_bootcmd`` stage (``cloud-init-local.service``, uptime ~7s)
    NetworkManager is not yet running, so ``nmcli connection reload`` is
    neither needed nor safe. NM will read the remaining (correct) profiles
    fresh when it starts later in the boot. Regression guard: ensure the
    old runcmd-era reload step is GONE from both roles."""
    yaml = pytest.importorskip("yaml")
    for role in (Role.MASTER, Role.SLAVE):
        out = generate_user_data("astromech", HASH, role=role)
        # Both the raw bytes and the parsed compound must be reload-free.
        assert _NMCLI_RELOAD not in out.decode("utf-8"), role
        parsed = yaml.safe_load(out)
        compound = parsed["bootcmd"][0]
        assert _NMCLI_RELOAD not in compound, role


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


# ── bootcmd marker-file guard (2026-06-06, cc_bootcmd re-fire) ──────────────
def test_bootcmd_is_marker_guarded():
    """The bootcmd must be wrapped in a marker-file shell guard so it executes
    EXACTLY ONCE per Pi. cloud-init's cc_bootcmd re-fires the bootcmd block
    on every boot; without the guard, boot 2 would wipe the NetworkManager
    profiles that firstboot just created on boot 1, bricking network
    reachability."""
    for role in (Role.MASTER, Role.SLAVE):
        out = generate_user_data("astromech", HASH, role=role).decode("utf-8")
        # Regression guard.
        assert "runcmd:" not in out, role
        # The literal short-circuit guard at the head of the compound.
        assert "[ -f /var/lib/astromech/runcmd_done ]" in out, role
        # The OR short-circuit operator (NOT &&) so the brace block only
        # runs when the marker is ABSENT.
        assert "[ -f /var/lib/astromech/runcmd_done ] ||" in out, role


def test_bootcmd_touches_marker_on_success():
    """The compound must finish by creating the marker via `mkdir -p ... &&
    touch ...` so the marker is set ONLY after every prior step succeeded.
    If any rm fails, the marker stays absent and the next boot retries —
    defensive belt-and-braces."""
    for role in (Role.MASTER, Role.SLAVE):
        out = generate_user_data("astromech", HASH, role=role).decode("utf-8")
        assert "runcmd:" not in out, role  # regression guard
        assert "mkdir -p /var/lib/astromech" in out, role
        assert "touch /var/lib/astromech/runcmd_done" in out, role
        # The mkdir / touch pair must be chained with && (not ;) so the
        # marker is not created if mkdir somehow fails.
        assert (
            "mkdir -p /var/lib/astromech && touch /var/lib/astromech/runcmd_done"
            in out
        ), role


def test_bootcmd_yaml_is_parseable_single_compound():
    """The whole bootcmd must be a SINGLE YAML list entry (the compound shell
    command), so the wipe either runs entirely or not at all — never partial."""
    yaml = pytest.importorskip("yaml")
    for role in (Role.MASTER, Role.SLAVE):
        out = generate_user_data("astromech", HASH, role=role)
        parsed = yaml.safe_load(out)
        assert isinstance(parsed, dict), role
        assert "bootcmd" in parsed, role
        # Regression guard: must no longer emit runcmd.
        assert "runcmd" not in parsed, role
        assert isinstance(parsed["bootcmd"], list), role
        assert len(parsed["bootcmd"]) == 1, role
        compound = parsed["bootcmd"][0]
        assert isinstance(compound, str), role
        # The compound must contain both the head guard and the tail touch.
        assert "[ -f /var/lib/astromech/runcmd_done ]" in compound, role
        assert "touch /var/lib/astromech/runcmd_done" in compound, role


def test_bootcmd_marker_guard_interpolates_username():
    """The marker-guarded compound must still interpolate the username into
    the authorized_keys path (HARD RULE: no hardcoded `astromech`). Verify
    via YAML parse so we know the compound is also still well-formed YAML."""
    yaml = pytest.importorskip("yaml")
    for role in (Role.MASTER, Role.SLAVE):
        out = generate_user_data("custom", HASH, role=role)
        parsed = yaml.safe_load(out)
        compound = parsed["bootcmd"][0]
        assert "rm -f /home/custom/.ssh/authorized_keys" in compound, role
        assert "/home/astromech/" not in compound, role


def test_bootcmd_marker_paths_consistent():
    """The marker path inside the guard head and at the touch tail must be
    the SAME path — otherwise the guard would never catch its own marker."""
    for role in (Role.MASTER, Role.SLAVE):
        out = generate_user_data("astromech", HASH, role=role).decode("utf-8")
        # Both must reference exactly the same canonical path.
        assert out.count("/var/lib/astromech/runcmd_done") >= 2, role


def test_bootcmd_uses_marker_file_path():
    """The marker file path must remain ``/var/lib/astromech/runcmd_done``
    (historical filename) even though the cloud-init hook moved from
    ``runcmd:`` to ``bootcmd:``. This preserves in-place upgrade safety for
    any Pi that already booted under the runcmd flow on 2026-06-05/06: it
    sees the existing marker on its first ``cc_bootcmd`` pass and stays
    no-op rather than re-wiping its working NM profiles."""
    yaml = pytest.importorskip("yaml")
    for role in (Role.MASTER, Role.SLAVE):
        out = generate_user_data("astromech", HASH, role=role)
        parsed = yaml.safe_load(out)
        compound = parsed["bootcmd"][0]
        # The exact stable marker path (filename intentionally kept).
        assert "/var/lib/astromech/runcmd_done" in compound, role
        # The new "bootcmd_done" filename must NOT have leaked in — backward
        # compat with in-flight Pis depends on the runcmd_done name.
        assert "bootcmd_done" not in compound, role


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
