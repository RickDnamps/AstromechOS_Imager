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

#: Marker file dropped after the bootcmd scrub finishes successfully. cloud-init
#: ``cc_bootcmd`` runs ``per-always`` (every boot) — like ``cc_scripts_user``
#: did for the old ``runcmd:`` block — so the guard is still required to make
#: the wipe a once-per-Pi operation. The filename ``runcmd_done`` (not
#: ``bootcmd_done``) is kept for backwards-compat with any in-flight Pi that
#: already booted under the older runcmd flow: an in-place upgrade must see the
#: existing marker and stay no-op. The marker is
#: created with ``&&`` inside the guard so it is set only after every scrub
#: step succeeded; if anything inside fails, the marker is NOT set and bootcmd
#: retries on the next boot. ``rm -f`` is idempotent so a retry is safe.
_RUNCMD_MARKER_DIR = "/var/lib/astromech"
_RUNCMD_MARKER = f"{_RUNCMD_MARKER_DIR}/runcmd_done"


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


def _build_bootcmd_guard(username: str, profile_basenames: tuple[str, ...]) -> str:
    """Build a single-line shell compound command, guarded by a marker file, so
    the stale-state scrub runs EXACTLY ONCE per Pi — not on every boot — AND
    runs EARLY enough (cloud-init-local stage, uptime ~7s) that it completes
    before NetworkManager starts.

    The older ``runcmd:`` implementation ran inside ``cc_scripts_user`` during
    ``cloud-final.service`` at uptime ~22s — racy with firstboot and (because
    the AstromechOS sister fix added ``After=cloud-final.service`` to
    ``astromech-firstboot.service``) created a startup ordering cycle through
    ``multi-user.target`` that systemd silently broke by dropping firstboot
    altogether. Switching to ``bootcmd:`` moves the wipe into
    ``cc_bootcmd`` which runs in ``cloud-init-local.service`` BEFORE
    NetworkManager has even read any profile — no race, no cycle.

    The compound is structured as::

        [ -f /var/lib/astromech/runcmd_done ] || { <scrub steps> ; \
            mkdir -p /var/lib/astromech && touch /var/lib/astromech/runcmd_done ; }

    * ``[ -f marker ] ||`` short-circuits the entire brace block once the
      marker exists (boot 2+ is a no-op — ``cc_bootcmd`` is also per-always).
    * The ``mkdir -p ... && touch ...`` runs LAST and is chained with ``&&``
      so the marker is only set on success. If any prior ``rm -f`` somehow
      fails (it won't — ``rm -f`` is idempotent), the marker is not written
      and the next boot retries. Defensive belt-and-braces.
    * Each statement inside the brace block is semicolon-terminated; bash
      requires a terminator before the closing brace of a brace group.
    * NO ``nmcli connection reload`` step — at the ``cloud-init-local`` stage
      NetworkManager is not yet running, so there is nothing to reload. NM
      will read the remaining (correct, Imager-baked) profiles when it starts
      later in the boot.

    The output is intentionally a single string (one YAML list entry) so the
    whole compound either runs or doesn't — no partial state where some
    profiles were wiped and others weren't.
    """
    parts = [f"rm -f /home/{username}/.ssh/authorized_keys"]
    parts.extend(
        f"rm -f {_NM_SYS_CONN_DIR}/{basename}" for basename in profile_basenames
    )
    parts.append(
        f"mkdir -p {_RUNCMD_MARKER_DIR} && touch {_RUNCMD_MARKER}"
    )
    inner = "; ".join(parts) + ";"
    return f"[ -f {_RUNCMD_MARKER} ] || {{ {inner} }}"


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

    Role-aware ``bootcmd``: the Golden Image bakes stale
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
      against the legacy master pubkey carrying over). NO
      ``nmcli connection reload`` is needed — at the ``cc_bootcmd`` stage
      NetworkManager is not yet running, so it will read the remaining
      (correct) profiles fresh when it starts later.

    ``bootcmd`` is wrapped in a marker-file guard (``/var/lib/astromech/
    runcmd_done`` — historical filename kept for in-place upgrade
    backwards-compat) so the scrub fires EXACTLY ONCE per Pi. cloud-init's
    ``cc_bootcmd`` runs ``per-always`` (every boot) — without the guard, boot
    2 would wipe the NetworkManager profiles that firstboot just created on
    boot 1, leaving the Pi unreachable. ``rm -f`` is idempotent so a
    marker-less retry on the next boot is safe.

    Why bootcmd instead of runcmd: the prior ``runcmd:`` implementation ran during
    ``cloud-final.service`` at uptime ~22s. The AstromechOS sister fix added
    ``After=cloud-final.service`` to ``astromech-firstboot.service``, but
    ``cloud-final.service`` itself declares ``After=multi-user.target`` and
    firstboot is ``WantedBy=multi-user.target`` — a startup ordering cycle
    that systemd silently broke by dropping firstboot. Moving the wipe to
    ``bootcmd:`` (runs in ``cloud-init-local.service`` at uptime ~7s, BEFORE
    NetworkManager and BEFORE firstboot is even queued) eliminates the race
    AND the cycle.

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
        Any other value (defensive) emits no bootcmd block.
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
    # Role-aware bootcmd: scrub stale NM profiles + stale authorized_keys at
    # first boot, wrapped in a marker-file guard so the whole compound runs
    # EXACTLY ONCE per Pi even though cloud-init's cc_bootcmd re-fires
    # bootcmd on every boot. cc_bootcmd runs in cloud-init-local.service
    # (uptime ~7s) BEFORE NetworkManager has loaded any profile and BEFORE
    # astromech-firstboot.service is queued — no race, no ordering cycle.
    # Defensive: only MASTER or SLAVE roles emit a bootcmd block; any other
    # value yields none.
    if role in (Role.MASTER, Role.SLAVE):
        if role is Role.MASTER:
            role_label = "MASTER"
            stale_nm_profiles = _STALE_MASTER_NM_PROFILES
        else:
            role_label = "SLAVE"
            stale_nm_profiles = _STALE_SLAVE_NM_PROFILES
        # The username is upstream-validated to POSIX login chars
        # ([a-z_][a-z0-9_-]*), so it carries neither YAML single quotes nor
        # shell metacharacters; we therefore safely embed it directly inside
        # the YAML single-quoted scalar AND the shell compound. (If the
        # validator ever loosens, _build_bootcmd_guard would need shell-quoting
        # added — flagged here.)
        guard = _build_bootcmd_guard(username, stale_nm_profiles)
        bootcmd_lines = [
            f"# {role_label}: scrub stale state baked into the Golden Image.",
            f"# Marker-guarded ({_RUNCMD_MARKER}) so the wipe runs exactly once",
            "# per Pi (cc_bootcmd re-fires bootcmd every boot). Runs in",
            "# cloud-init-local stage BEFORE NetworkManager starts.",
            "bootcmd:",
            f"  - {_yaml_squote(guard)}",
            "",
        ]
        lines.extend(bootcmd_lines)
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
