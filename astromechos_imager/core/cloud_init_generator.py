"""Generate cloud-init NoCloud seed files + the cmdline.txt tokens that
activate them — the official Raspberry Pi Imager flow for Raspberry Pi OS
Trixie, 100% on the FAT boot partition, leaving the Golden Image untouched.

How it works (verified against an official rpi-imager Trixie card):

  * The OS image ships ``/etc/cloud/cloud.cfg.d/99_raspberry-pi.cfg`` with
    ``datasource_list: [NoCloud, None]`` + ``seedfrom: file:///boot/firmware``,
    so cloud-init reads ``user-data`` / ``meta-data`` from the FAT boot
    partition on first boot. We just drop those two files there.

  * Every flash carries a UNIQUE ``instance-id`` (``rpi-imager-<epoch-ms>``)
    in BOTH ``meta-data`` and the kernel cmdline (``ds=nocloud;i=...``). A new
    instance-id makes cloud-init treat the boot as a fresh instance and re-run
    the per-instance modules (``users``, ``set_passwords``) — so the account
    + password are applied even though the Golden's UID-1000 user already
    exists. (NoCloud docs: "the instance-id provided is what is used to
    determine if this is 'first boot'".)

  * Rootfs grows natively: the bare ``resize`` cmdline token triggers the
    initramfs ``local-premount/resize_early`` hook (partition grow via
    ``parted``); cloud-init's ``cc_resizefs`` then grows the filesystem.
    NO ``init=`` (the dead/dangerous PID-1 hack) and NO ``systemd.run``
    (the abandoned firstrun.sh mechanism) are ever written.

Scope: cloud-init owns the generic account + password (what cold surgery /
firstrun.sh used to do) and the resize. Hostname, Wi-Fi (dual-WLAN), SSH
keys, the Master<->Slave hotspot and the role marker stay with the
AstromechOS first-boot bundle (CLAUDE.md Invariants #2/#4); they are
intentionally NOT set here, so the two mechanisms never fight.
"""
from __future__ import annotations

from astromechos_imager.core.models import Role

#: Directory NetworkManager scans for system connection profiles. Stale
#: profiles baked into the Golden Image live here and would outrank the
#: per-deployment ones written by AstromechOS firstboot if left in place.
_NM_SYS_CONN_DIR = "/etc/NetworkManager/system-connections"

#: Stale NetworkManager profiles baked into the Golden Image on the MASTER
#: role: the wlan0 AP profile (legacy ``astromech``/``astropass`` SSID/PSK)
#: and the wlan1 client profile pointing at the previous operator's home
#: WiFi. Both must be removed at first boot so the AstromechOS firstboot
#: bundle's per-deployment profiles win.
_STALE_MASTER_NM_PROFILES = (
    "astromech-hotspot.nmconnection",
    "astromech-internet.nmconnection",
    "r2d2-internet.nmconnection",
)

#: Stale NetworkManager profiles baked into the Golden Image on the SLAVE
#: role: the wlan0 client profile pointing at the LEGACY master's hotspot.
#: It carries ``autoconnect-priority=100`` plus the legacy SSID/PSK
#: ``astromech``/``astropass`` and would otherwise outrank the
#: netplan-generated profile pointing at the real Imager-baked hotspot SSID.
#: ``r2d2-master-hotspot`` is the post-rename legacy basename we may also see.
_STALE_SLAVE_NM_PROFILES = (
    "astromech-master-hotspot.nmconnection",
    "r2d2-master-hotspot.nmconnection",
)

#: Backwards-compat alias for the original constant — preserved so existing
#: imports / tests that reference the single-profile name keep working.
_STALE_SLAVE_NM_PROFILE = f"{_NM_SYS_CONN_DIR}/{_STALE_SLAVE_NM_PROFILES[0]}"

#: Bare cmdline token that triggers the native initramfs partition-resize hook
#: (``scripts/local-premount/resize_early``). Harmless if unrecognised — the
#: kernel never tries to exec it, so (unlike ``init=``) it cannot panic PID 1.
RESIZE_TOKEN = "resize"


def generate_instance_id(timestamp_ms: int) -> str:
    """Per-flash cloud-init instance-id in the official rpi-imager format
    ``rpi-imager-<epoch-milliseconds>``.

    A fresh value on every flash forces cloud-init to treat each card as a new
    instance and re-run its per-instance modules, which is what applies the
    account + password on top of the Golden Image's pre-existing user.
    """
    return f"rpi-imager-{int(timestamp_ms)}"


def generate_meta_data(instance_id: str) -> bytes:
    """NoCloud ``meta-data`` — only the instance-id.

    We deliberately omit ``local-hostname``: the hostname is owned by the
    AstromechOS first-boot bundle (set per role), and setting it here too
    would make cloud-init and the bundle fight over it.
    """
    return f"instance-id: {instance_id}\n".encode("ascii")


def _yaml_squote(value: str) -> str:
    """Single-quote a scalar for YAML (a literal single quote becomes '')."""
    return "'" + value.replace("'", "''") + "'"


def generate_user_data(
    username: str,
    crypt_password_hash: str,
    *,
    role: Role = Role.MASTER,
) -> bytes:
    """NoCloud ``#cloud-config`` that RECONFIGURES the Golden's existing
    UID-1000 user in place — it never creates a parallel account.

    Strategy (the Golden ships AstromechOS pre-installed + configured for its
    UID-1000 user, exactly like a community-prepared rpi-imager image):

    * ``users: []`` — cloud-init creates NO account, not even the distro
      default. The Golden's UID-1000 user keeps its home, groups, sudo rights
      and the whole AstromechOS install untouched (its existing sudo is
      preserved — we do not, and need not, re-grant it).
    * ``chpasswd`` (``type: hash``) — sets the SHA-512 crypt password on that
      EXISTING user, by name. cloud-init writes /etc/shadow on first boot; we
      never touch it offline and never rename anything.
    * ``ssh_pwauth: true`` — allows password SSH (keys still come from the
      AstromechOS firstboot bundle).

    IMPORTANT — ``username`` MUST be the Golden's actual UID-1000 login.
    ``chpasswd`` targets users by NAME and silently skips a name that does not
    exist (no password change, and — by design — no new user created). The
    image's cloud-init ``default_user`` (``pi``) is NOT the UID-1000 user
    (e.g. ``artoo``), so default-user shortcuts cannot reach UID-1000 — only
    the explicit name works.

    Wi-Fi, SSH keys, hostname, hotspot and role stay with the AstromechOS
    firstboot bundle (Invariant #2) and are intentionally NOT emitted here.

    Role-aware ``runcmd`` (since 2026-06-05): the Golden Image bakes stale
    NetworkManager profiles AND a stale ``~/.ssh/authorized_keys`` (carrying
    the previous master's ed25519 pubkey) into UID-1000's home. Both must be
    wiped at first boot so the AstromechOS firstboot bundle's per-deployment
    SSH keys + WiFi profiles win. The scrubs are role-specific:

    * MASTER: removes ``astromech-hotspot.nmconnection`` (wlan0 AP, legacy
      ``astromech``/``astropass`` SSID/PSK) and ``astromech-internet.nmconnection``
      / ``r2d2-internet.nmconnection`` (wlan1 client, carrying the previous
      operator's home WiFi creds).
    * SLAVE: removes ``astromech-master-hotspot.nmconnection`` (and its
      post-rename twin ``r2d2-master-hotspot.nmconnection``) — the wlan0
      client profile pointing at the LEGACY master's hotspot SSID with
      ``autoconnect-priority=100`` which would otherwise outrank the
      netplan-generated profile pointing at the real Imager-baked SSID.
    * Both roles: ``rm -f /home/<username>/.ssh/authorized_keys`` (defense
      against the legacy master pubkey carrying over) + a final
      ``nmcli connection reload`` so NetworkManager drops the in-memory
      profiles whose backing files just disappeared.

    ``runcmd`` runs once per instance-id and ``rm -f`` is idempotent — a
    freshly-baked Golden that no longer ships the files just sees no-ops.

    Parameters
    ----------
    username:
        The Golden Image's existing UID-1000 login name to reconfigure. Also
        interpolated into the ``/home/<username>/.ssh/authorized_keys`` scrub
        path (HARD RULE: never hardcode ``astromech``).
    crypt_password_hash:
        Pre-computed ``$6$...`` SHA-512 crypt hash (from ``keygen``).
    role:
        Target role for this card. ``Role.MASTER`` (the default) emits the
        master-side NM scrub; ``Role.SLAVE`` emits the slave-side NM scrub.
        Any other value (defensive) emits no runcmd block.
    """
    u = _yaml_squote(username)
    h = _yaml_squote(crypt_password_hash)
    lines = [
        "#cloud-config",
        "# AstromechOS Imager — reconfigure the Golden's existing UID-1000 user.",
        "# Applied once per the unique instance-id in meta-data / cmdline.",
        "",
        "# Create NO account (not even the distro default): the AstromechOS",
        "# user already exists in the Golden with its home, groups and sudo.",
        "users: []",
        "",
        "# Set the password on the EXISTING user, by name — no /etc/shadow edit",
        "# by us, no rename, the AstromechOS install left fully intact.",
        "chpasswd:",
        "  expire: false",
        "  users:",
        f"    - name: {u}",
        f"      password: {h}",
        "      type: hash",
        "",
        "ssh_pwauth: true",
        "",
    ]
    # Role-aware runcmd: scrub stale NM profiles + stale authorized_keys at
    # first boot. rm -f is idempotent (a freshly-baked Golden that no longer
    # ships these files just sees no-ops); runcmd runs once per instance-id,
    # so a re-flash with a new id re-applies the cleanup. Defensive: only
    # MASTER or SLAVE roles emit a runcmd block; any other value yields none.
    if role in (Role.MASTER, Role.SLAVE):
        if role is Role.MASTER:
            role_label = "MASTER"
            stale_nm_profiles = _STALE_MASTER_NM_PROFILES
        else:
            role_label = "SLAVE"
            stale_nm_profiles = _STALE_SLAVE_NM_PROFILES
        # YAML-safe interpolation of the username inside the single-quoted
        # runcmd scalar: a literal single quote in YAML single-quoted scalars
        # is escaped by doubling. We do NOT pass the username through the
        # shell (cloud-init's runcmd list form is execve'd directly when each
        # item is a list, but when it's a string it goes through sh -c — so
        # we also keep the path shell-safe by relying on the username
        # validator (POSIX [a-z_][a-z0-9_-]*) upstream).
        u_yaml = username.replace("'", "''")
        runcmd_lines = [
            f"# {role_label}: scrub stale state baked into the Golden Image.",
            "runcmd:",
            # Common to both roles: wipe the legacy authorized_keys so the
            # previous master's pubkey cannot reach this card; firstboot will
            # write fresh per-deployment keys.
            f"  - 'rm -f /home/{u_yaml}/.ssh/authorized_keys'",
        ]
        # Per-role NM profile scrub (basename joined with the NM dir).
        for basename in stale_nm_profiles:
            runcmd_lines.append(f"  - 'rm -f {_NM_SYS_CONN_DIR}/{basename}'")
        # Final, common: force NetworkManager to drop the in-memory profiles
        # whose backing files just disappeared.
        runcmd_lines.append("  - 'nmcli connection reload'")
        runcmd_lines.append("")
        lines.extend(runcmd_lines)
    return ("\n".join(lines)).encode("utf-8")


#: Minimal valid NoCloud user-data when there is no account to set — keeps the
#: seed well-formed so cloud-init still runs (and grows the filesystem).
EMPTY_USER_DATA = b"#cloud-config\n"


def build_cmdline(cmdline_bytes: bytes, instance_id: str) -> bytes:
    """Rewrite cmdline.txt for the cloud-init flow. Idempotent + self-cleaning.

    * Strips ANY ``init=`` token (the dead PID-1 resize hack — a wrong path
      bricks first boot).
    * Strips the abandoned firstrun.sh trigger (``systemd.run*`` and
      ``systemd.unit=kernel-command-line.target``).
    * Strips any prior ``ds=nocloud...`` token (re-added with the fresh id).
    * Ensures exactly one bare ``resize`` token (native partition grow).
    * Appends ``ds=nocloud;i=<instance_id>`` (selects NoCloud + pins the id).
    """
    text = cmdline_bytes.decode("ascii", errors="strict").rstrip("\n").rstrip()
    kept: list[str] = []
    for tok in text.split():
        if tok.startswith("init="):
            continue
        if tok.startswith("systemd.run"):
            continue
        if tok == "systemd.unit=kernel-command-line.target":
            continue
        if tok.startswith("ds=nocloud"):
            continue
        if tok == RESIZE_TOKEN:
            continue  # de-dupe; re-added exactly once below
        kept.append(tok)
    kept.append(RESIZE_TOKEN)
    kept.append(f"ds=nocloud;i={instance_id}")
    return (" ".join(kept) + "\n").encode("ascii")
