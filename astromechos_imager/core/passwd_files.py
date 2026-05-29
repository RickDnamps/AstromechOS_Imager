"""Pure-Python parsers, serializers, and rename helpers for /etc/passwd, /etc/shadow,
and /etc/group.

All public functions take and return ``bytes`` (or ``list[*Row]`` intermediates).
No ext4 / subprocess dependency at this layer.
"""
from __future__ import annotations

from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────────────────────
# Row dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PasswdRow:
    name: str
    pw: str
    uid: int
    gid: int
    gecos: str
    home: str
    shell: str


@dataclass(frozen=True)
class ShadowRow:
    name: str
    hash: str
    lastchg: str
    min_: str
    max_: str
    warn: str
    inactive: str
    expire: str
    reserved: str


@dataclass(frozen=True)
class GroupRow:
    name: str
    pw: str
    gid: int
    members: tuple[str, ...]


# ─────────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────────


def parse_passwd(content: bytes) -> list[PasswdRow]:
    """Parse /etc/passwd bytes into a list of PasswdRow objects.

    Empty lines are skipped; order of non-empty rows is preserved.
    """
    rows: list[PasswdRow] = []
    for line in content.decode("utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(":")
        if len(parts) != 7:
            raise ValueError(f"Invalid passwd line: {line!r}")
        rows.append(
            PasswdRow(
                name=parts[0],
                pw=parts[1],
                uid=int(parts[2]),
                gid=int(parts[3]),
                gecos=parts[4],
                home=parts[5],
                shell=parts[6],
            )
        )
    return rows


def parse_shadow(content: bytes) -> list[ShadowRow]:
    """Parse /etc/shadow bytes into a list of ShadowRow objects.

    Empty lines are skipped; order of non-empty rows is preserved.
    """
    rows: list[ShadowRow] = []
    for line in content.decode("utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(":")
        if len(parts) != 9:
            raise ValueError(f"Invalid shadow line: {line!r}")
        rows.append(
            ShadowRow(
                name=parts[0],
                hash=parts[1],
                lastchg=parts[2],
                min_=parts[3],
                max_=parts[4],
                warn=parts[5],
                inactive=parts[6],
                expire=parts[7],
                reserved=parts[8],
            )
        )
    return rows


def parse_group(content: bytes) -> list[GroupRow]:
    """Parse /etc/group bytes into a list of GroupRow objects.

    Empty lines are skipped; order of non-empty rows is preserved.
    """
    rows: list[GroupRow] = []
    for line in content.decode("utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(":")
        if len(parts) != 4:
            raise ValueError(f"Invalid group line: {line!r}")
        raw_members = parts[3]
        members: tuple[str, ...]
        if raw_members.strip():
            members = tuple(m for m in raw_members.split(",") if m)
        else:
            members = ()
        rows.append(
            GroupRow(
                name=parts[0],
                pw=parts[1],
                gid=int(parts[2]),
                members=members,
            )
        )
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────


def serialize_passwd(rows: list[PasswdRow]) -> bytes:
    """Serialize PasswdRow list to /etc/passwd bytes.

    Every row ends with ``\\n``. No trailing blank line.
    """
    lines = []
    for r in rows:
        lines.append(
            f"{r.name}:{r.pw}:{r.uid}:{r.gid}:{r.gecos}:{r.home}:{r.shell}\n"
        )
    return "".join(lines).encode("utf-8")


def serialize_shadow(rows: list[ShadowRow]) -> bytes:
    """Serialize ShadowRow list to /etc/shadow bytes.

    Every row ends with ``\\n``. No trailing blank line.
    """
    lines = []
    for r in rows:
        lines.append(
            f"{r.name}:{r.hash}:{r.lastchg}:{r.min_}:{r.max_}"
            f":{r.warn}:{r.inactive}:{r.expire}:{r.reserved}\n"
        )
    return "".join(lines).encode("utf-8")


def serialize_group(rows: list[GroupRow]) -> bytes:
    """Serialize GroupRow list to /etc/group bytes.

    Every row ends with ``\\n``. No trailing blank line.
    """
    lines = []
    for r in rows:
        members_str = ",".join(r.members)
        lines.append(f"{r.name}:{r.pw}:{r.gid}:{members_str}\n")
    return "".join(lines).encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Rename helpers
# ─────────────────────────────────────────────────────────────────────────────


def rename_user_in_passwd(
    rows: list[PasswdRow], old: str, new: str
) -> list[PasswdRow]:
    """Return a new list with the UID-1000 row renamed from *old* to *new*.

    The row's ``.home`` is rewritten from ``/home/<old>`` to ``/home/<new>``.
    All other rows are returned unchanged.

    Raises ``ValueError`` if no UID-1000 row exists or its name does not
    match *old*.
    """
    uid_row = next((r for r in rows if r.uid == 1000), None)
    if uid_row is None or uid_row.name != old:
        raise ValueError(
            f"No UID-1000 row with name {old!r} found in /etc/passwd"
        )
    result = []
    for r in rows:
        if r.uid == 1000 and r.name == old:
            new_home = r.home.replace(f"/home/{old}", f"/home/{new}", 1)
            result.append(
                PasswdRow(
                    name=new,
                    pw=r.pw,
                    uid=r.uid,
                    gid=r.gid,
                    gecos=r.gecos,
                    home=new_home,
                    shell=r.shell,
                )
            )
        else:
            result.append(r)
    return result


def rename_user_in_shadow(
    rows: list[ShadowRow], old: str, new: str, new_crypt: str
) -> list[ShadowRow]:
    """Return a new list with the shadow row for *old* renamed to *new* and its
    password hash replaced with *new_crypt*.

    Raises ``ValueError`` if no row named *old* exists.
    """
    if not any(r.name == old for r in rows):
        raise ValueError(f"No shadow row with name {old!r}")
    result = []
    for r in rows:
        if r.name == old:
            result.append(
                ShadowRow(
                    name=new,
                    hash=new_crypt,
                    lastchg=r.lastchg,
                    min_=r.min_,
                    max_=r.max_,
                    warn=r.warn,
                    inactive=r.inactive,
                    expire=r.expire,
                    reserved=r.reserved,
                )
            )
        else:
            result.append(r)
    return result


def rename_user_in_group(
    rows: list[GroupRow], old: str, new: str
) -> list[GroupRow]:
    """Return a new list with:

    * Any group whose ``.name == old`` renamed to *new* (primary-group
      convention — Pi OS names the primary group after the user).
    * Any group whose ``.members`` contains *old* rewritten to *new*.

    Raises ``ValueError`` if *old* does not appear as a group name OR as a
    member in any row (i.e. the user is completely unknown).
    """
    appears = any(
        r.name == old or old in r.members
        for r in rows
    )
    if not appears:
        raise ValueError(f"User {old!r} not found in any group row")

    result = []
    for r in rows:
        new_name = new if r.name == old else r.name
        new_members = tuple(new if m == old else m for m in r.members)
        result.append(
            GroupRow(
                name=new_name,
                pw=r.pw,
                gid=r.gid,
                members=new_members,
            )
        )
    return result
