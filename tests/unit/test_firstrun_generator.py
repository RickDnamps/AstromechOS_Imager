"""Unit tests for the rpi-imager-style firstrun.sh generator (FAT, no ext4)."""
from __future__ import annotations

from astromechos_imager.core.firstrun_generator import (
    FIRSTRUN_CMDLINE_TRIGGER,
    append_firstrun_trigger,
    generate_firstrun_sh,
)

HASH = "$6$abcdefghij$1234567890abcdefghABCDEFGH/.ZzYyXx"


def test_firstrun_contains_user_password_and_self_destruct():
    sh = generate_firstrun_sh("astromech", HASH).decode("utf-8")
    # shebang + the official userconf-pi helper path + chpasswd fallback
    assert sh.startswith("#!/bin/sh")
    assert "/usr/lib/userconf-pi/userconf" in sh
    assert "chpasswd -e" in sh
    # rename helpers (rpi-imager parity)
    assert "usermod -l" in sh
    assert "usermod -m -d /home/astromech" in sh
    assert "groupmod -n" in sh
    # the target user + hash both appear (single-quoted)
    assert "'astromech'" in sh
    assert "'" + HASH + "'" in sh
    # self-destruct, exactly like the official tool
    assert "rm -f /boot/firstrun.sh" in sh
    assert "sed -i 's| systemd.run.*||g' /boot/cmdline.txt" in sh


def test_firstrun_is_lf_only_and_utf8():
    raw = generate_firstrun_sh("astromech", HASH)
    assert b"\r" not in raw          # LF only — a CRLF shebang breaks /bin/sh
    raw.decode("utf-8")              # valid UTF-8


def test_firstrun_shell_quotes_single_quote_in_username():
    # Defensive: an embedded single quote must be escaped, not break the script.
    sh = generate_firstrun_sh("o'brien", HASH).decode("utf-8")
    assert "'o'\\''brien'" in sh


def test_append_trigger_adds_once_and_is_idempotent():
    base = b"console=tty1 root=PARTUUID=aa-02 rootwait\n"
    once = append_firstrun_trigger(base)
    assert b"systemd.run=/boot/firstrun.sh" in once
    assert once.endswith(b"\n")
    # idempotent: second call returns byte-identical input
    twice = append_firstrun_trigger(once)
    assert twice == once
    # exactly one trigger
    assert once.decode().count("systemd.run=/boot/firstrun.sh") == 1


def test_trigger_constant_shape():
    # The official fragment, verbatim (leading space; isolated run + reboot).
    assert FIRSTRUN_CMDLINE_TRIGGER == (
        " systemd.run=/boot/firstrun.sh"
        " systemd.run_success_action=reboot"
        " systemd.unit=kernel-command-line.target"
    )
