"""Unit tests for core/passwd_files.py — parsers, serializers, rename helpers."""
from __future__ import annotations

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from astromechos_imager.core.passwd_files import (
    GroupRow,
    PasswdRow,
    ShadowRow,
    parse_group,
    parse_passwd,
    parse_shadow,
    rename_user_in_group,
    rename_user_in_passwd,
    rename_user_in_shadow,
    serialize_group,
    serialize_passwd,
    serialize_shadow,
)


# ────────────────────────────────────────────────────────────────
# Hypothesis property tests — roundtrip
# ────────────────────────────────────────────────────────────────

NAME_ALPHABET = string.ascii_letters + string.digits + "_-"


@given(
    st.text(alphabet=NAME_ALPHABET, min_size=1, max_size=31)
)
@settings(max_examples=200)
def test_passwd_roundtrip(name: str) -> None:
    row = PasswdRow(
        name=name, pw="x", uid=1000, gid=1000,
        gecos="", home=f"/home/{name}", shell="/bin/bash",
    )
    out = parse_passwd(serialize_passwd([row]))
    assert out == [row]


_HASH_SAFE = "".join(
    c for c in string.printable
    if c not in (":", "\n", "\r", "\x0b", "\x0c")
)


@given(
    st.text(alphabet=NAME_ALPHABET, min_size=1, max_size=31),
    st.text(alphabet=_HASH_SAFE, min_size=0, max_size=100),
)
@settings(max_examples=200)
def test_shadow_roundtrip(name: str, hash_: str) -> None:
    row = ShadowRow(
        name=name, hash=hash_, lastchg="19000",
        min_="0", max_="99999", warn="7",
        inactive="", expire="", reserved="",
    )
    out = parse_shadow(serialize_shadow([row]))
    assert out == [row]


@given(
    st.text(alphabet=NAME_ALPHABET, min_size=1, max_size=31)
)
@settings(max_examples=200)
def test_group_roundtrip(name: str) -> None:
    row = GroupRow(name=name, pw="x", gid=1000, members=())
    out = parse_group(serialize_group([row]))
    assert out == [row]


# ────────────────────────────────────────────────────────────────
# Empty-line skipping
# ────────────────────────────────────────────────────────────────

def test_parse_passwd_skips_empty_lines() -> None:
    content = b"\nroot:x:0:0:root:/root:/bin/bash\n\npi:x:1000:1000:,,,:/home/pi:/bin/bash\n\n"
    rows = parse_passwd(content)
    assert len(rows) == 2
    assert rows[0].name == "root"
    assert rows[1].name == "pi"


def test_parse_shadow_skips_empty_lines() -> None:
    content = b"\nroot:*:19000:0:99999:7:::\n\npi:!:19000:0:99999:7:::\n"
    rows = parse_shadow(content)
    assert len(rows) == 2


def test_parse_group_skips_empty_lines() -> None:
    content = b"\nroot:x:0:\n\npi:x:1000:\n"
    rows = parse_group(content)
    assert len(rows) == 2


# ────────────────────────────────────────────────────────────────
# Serializer trailing-newline contract
# ────────────────────────────────────────────────────────────────

def test_serialize_passwd_trailing_newline() -> None:
    rows = [PasswdRow("root", "x", 0, 0, "root", "/root", "/bin/bash")]
    out = serialize_passwd(rows).decode()
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_serialize_shadow_trailing_newline() -> None:
    rows = [ShadowRow("root", "*", "19000", "0", "99999", "7", "", "", "")]
    out = serialize_shadow(rows).decode()
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_serialize_group_trailing_newline() -> None:
    rows = [GroupRow("root", "x", 0, ())]
    out = serialize_group(rows).decode()
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


# ────────────────────────────────────────────────────────────────
# rename_user_in_passwd — golden cases
# ────────────────────────────────────────────────────────────────

PASSWD_CONTENT = (
    b"root:x:0:0:root:/root:/bin/bash\n"
    b"pi:x:1000:1000:,,,:/home/pi:/bin/bash\n"
)


def test_rename_passwd_uid_1000() -> None:
    rows = parse_passwd(PASSWD_CONTENT)
    new_rows = rename_user_in_passwd(rows, "pi", "testuser")
    out = serialize_passwd(new_rows).decode()
    assert "pi:x:1000" not in out
    assert "testuser:x:1000:1000:,,,:/home/testuser:/bin/bash" in out
    assert "root:x:0:0:root:/root:/bin/bash" in out  # untouched


def test_rename_passwd_home_rewritten() -> None:
    rows = parse_passwd(PASSWD_CONTENT)
    new_rows = rename_user_in_passwd(rows, "pi", "testuser")
    uid_row = next(r for r in new_rows if r.uid == 1000)
    assert uid_row.home == "/home/testuser"
    assert uid_row.name == "testuser"


def test_rename_passwd_raises_on_missing() -> None:
    rows = parse_passwd(b"root:x:0:0:root:/root:/bin/bash\n")
    with pytest.raises(ValueError, match="nope"):
        rename_user_in_passwd(rows, "nope", "x")


def test_rename_passwd_raises_when_uid1000_name_mismatch() -> None:
    """Old name supplied but uid-1000 row has a different name."""
    rows = parse_passwd(PASSWD_CONTENT)
    with pytest.raises(ValueError):
        rename_user_in_passwd(rows, "notpi", "testuser")


# ────────────────────────────────────────────────────────────────
# rename_user_in_shadow — golden cases
# ────────────────────────────────────────────────────────────────

SHADOW_CONTENT = (
    b"root:*:19000:0:99999:7:::\n"
    b"pi:OLD_HASH:19000:0:99999:7:::\n"
)


def test_rename_shadow_golden() -> None:
    rows = parse_shadow(SHADOW_CONTENT)
    new_rows = rename_user_in_shadow(rows, "pi", "testuser", "$6$salt$hash")
    out = serialize_shadow(new_rows).decode()
    assert "pi:" not in out
    assert "testuser:$6$salt$hash:" in out
    assert "root:*:" in out  # untouched


def test_rename_shadow_raises_on_missing() -> None:
    rows = parse_shadow(SHADOW_CONTENT)
    with pytest.raises(ValueError, match="nope"):
        rename_user_in_shadow(rows, "nope", "testuser", "$6$salt$hash")


# ────────────────────────────────────────────────────────────────
# rename_user_in_group — golden cases
# ────────────────────────────────────────────────────────────────

GROUP_CONTENT = (
    b"root:x:0:\n"
    b"pi:x:1000:\n"
    b"sudo:x:27:pi\n"     # pi is a member
    b"video:x:44:pi\n"    # pi is a member
)


def test_rename_group_primary_group() -> None:
    rows = parse_group(GROUP_CONTENT)
    new_rows = rename_user_in_group(rows, "pi", "testuser")
    names = [r.name for r in new_rows]
    assert "pi" not in names
    assert "testuser" in names


def test_rename_group_memberships() -> None:
    rows = parse_group(GROUP_CONTENT)
    new_rows = rename_user_in_group(rows, "pi", "testuser")
    sudo_row = next(r for r in new_rows if r.name == "sudo")
    video_row = next(r for r in new_rows if r.name == "video")
    assert "testuser" in sudo_row.members
    assert "pi" not in sudo_row.members
    assert "testuser" in video_row.members


def test_rename_group_root_untouched() -> None:
    rows = parse_group(GROUP_CONTENT)
    new_rows = rename_user_in_group(rows, "pi", "testuser")
    root_row = next(r for r in new_rows if r.name == "root")
    assert root_row == rows[0]  # completely unchanged


def test_rename_group_raises_on_missing() -> None:
    rows = parse_group(GROUP_CONTENT)
    with pytest.raises(ValueError, match="nope"):
        rename_user_in_group(rows, "nope", "testuser")


# ────────────────────────────────────────────────────────────────
# Group members round-trip with multiple members
# ────────────────────────────────────────────────────────────────

def test_group_members_roundtrip() -> None:
    row = GroupRow(name="sudo", pw="x", gid=27, members=("pi", "admin", "user"))
    out = parse_group(serialize_group([row]))
    assert out[0].members == ("pi", "admin", "user")


def test_group_empty_members_roundtrip() -> None:
    row = GroupRow(name="root", pw="x", gid=0, members=())
    out = parse_group(serialize_group([row]))
    assert out[0].members == ()
