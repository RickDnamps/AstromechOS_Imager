"""Generate a Raspberry Pi OS ``firstrun.sh`` for first-boot account setup.

This is a faithful port of the official Raspberry Pi Imager mechanism
(``rpi-imager`` ``CustomisationGenerator::generateSystemdScript`` +
``DownloadThread::_customizeImage``). It is **100% FAT-partition** work — no
ext4 / debugfs / e2fsprogs involved:

  1. The Imager writes ``firstrun.sh`` to the FAT boot partition root.
  2. The Imager appends to ``cmdline.txt``::

        systemd.run=/boot/firstrun.sh systemd.run_success_action=reboot \
        systemd.unit=kernel-command-line.target

     so the script runs ONCE, isolated, on first boot, then the Pi reboots.
  3. ``firstrun.sh`` sets the UID-1000 username + password (via the official
     ``userconf-pi`` helper, with a ``chpasswd -e`` / ``usermod`` fallback)
     and then deletes itself + strips ``systemd.run`` from ``cmdline.txt``.

Verified against the official tool: this exact mechanism (with the literal
``/boot/...`` paths, no ``/boot/firmware`` special-case) is what Raspberry Pi
Imager uses for Raspberry Pi OS — including the Trixie image this project
targets — so it is known-compatible.
"""
from __future__ import annotations

#: The exact kernel-cmdline fragment the official tool appends so firstrun.sh
#: runs isolated on first boot and the Pi reboots afterwards. Leading space is
#: intentional (it is concatenated after the existing cmdline).
FIRSTRUN_CMDLINE_TRIGGER = (
    " systemd.run=/boot/firstrun.sh"
    " systemd.run_success_action=reboot"
    " systemd.unit=kernel-command-line.target"
)


def _shell_squote(value: str) -> str:
    """Single-quote a value for safe POSIX-sh use (handles embedded quotes).

    Mirrors the official generator's ``shellQuote``: wrap in single quotes and
    escape any embedded single quote as ``'\\''``.
    """
    return "'" + value.replace("'", "'\\''") + "'"


def generate_firstrun_sh(username: str, crypt_password_hash: str) -> bytes:
    """Build the ``firstrun.sh`` body that renames UID-1000 and sets its password.

    Parameters
    ----------
    username:
        Desired UID-1000 login name (e.g. ``astromech``).
    crypt_password_hash:
        Pre-computed crypt hash (``$6$...`` SHA-512), consumed by
        ``chpasswd -e`` / ``userconf``.

    Returns
    -------
    bytes
        UTF-8, LF-terminated script ready to write to the FAT boot partition.
    """
    u = _shell_squote(username)
    h = _shell_squote(crypt_password_hash)
    # Mirrors the official rpi-imager generateSystemdScript user/password block.
    # On Raspberry Pi OS the userconf-pi branch is taken and does everything
    # (rename + password + autologin fixups); the else branch is the generic
    # fallback. Self-destruct cleans BOTH /boot and /boot/firmware so a stale
    # trigger can never re-arm (Trixie mounts the FAT at /boot/firmware).
    lines = [
        "#!/bin/sh",
        "",
        "set +e",
        "",
        "FIRSTUSER=$(getent passwd 1000 | cut -d: -f1)",
        "FIRSTUSERHOME=$(getent passwd 1000 | cut -d: -f6)",
        "",
        "if [ -f /usr/lib/userconf-pi/userconf ]; then",
        f"   /usr/lib/userconf-pi/userconf {u} {h}",
        "else",
        f'   echo "$FIRSTUSER:"{h} | chpasswd -e',
        f"   if [ \"$FIRSTUSER\" != {u} ]; then",
        f"      usermod -l {u} \"$FIRSTUSER\"",
        f"      usermod -m -d /home/{username} {u}",
        f"      groupmod -n {u} \"$FIRSTUSER\"",
        "      if grep -q \"^autologin-user=\" /etc/lightdm/lightdm.conf 2>/dev/null; then",
        f"         sed -i \"s/^autologin-user=.*/autologin-user={username}/\" /etc/lightdm/lightdm.conf",
        "      fi",
        "      if [ -f /etc/systemd/system/getty@tty1.service.d/autologin.conf ]; then",
        f"         sed -i \"s/$FIRSTUSER/{username}/\" /etc/systemd/system/getty@tty1.service.d/autologin.conf",
        "      fi",
        "      if [ -f /etc/sudoers.d/010_pi-nopasswd ]; then",
        f"         sed -i \"s/^$FIRSTUSER /{username} /\" /etc/sudoers.d/010_pi-nopasswd",
        "      fi",
        "   fi",
        "fi",
        "",
        "rm -f /boot/firstrun.sh /boot/firmware/firstrun.sh",
        "for _c in /boot/cmdline.txt /boot/firmware/cmdline.txt; do",
        "   [ -f \"$_c\" ] && sed -i 's| systemd.run.*||g' \"$_c\"",
        "done",
        "exit 0",
        "",
    ]
    return ("\n".join(lines)).encode("utf-8")


def append_firstrun_trigger(cmdline_bytes: bytes) -> bytes:
    """Append the ``systemd.run=/boot/firstrun.sh ...`` trigger to cmdline.txt.

    Idempotent: returns the input unchanged (byte-identical) if the trigger is
    already present, so re-running customize never duplicates it.
    """
    text = cmdline_bytes.decode("ascii", errors="strict").rstrip("\n").rstrip()
    if "systemd.run=/boot/firstrun.sh" in text:
        return cmdline_bytes
    return (text + FIRSTRUN_CMDLINE_TRIGGER + "\n").encode("ascii")
