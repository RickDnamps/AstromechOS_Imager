"""Image role + integrity validation.

Two layers protect the operator from flashing the wrong file or a
corrupted one:

1. **Role marker** — a small ``/astromech_role.json`` written into the
   FAT32 boot partition when the image is baked. Schema:

       {"role": "master" | "slave",
        "project": "AstromechOS",
        "version": "2.0",
        ...optional extra keys...}

   Every divergence from this schema is a HARD BLOCK (raises a subclass
   of ``ImageRoleValidationError`` from ``core.errors``); higher layers
   — the Wizard preview, the Flash preflight — decide how to surface or
   soften the block.

2. **Filename hint** — quick regex on the basename used by the Wizard
   when the marker is missing. Aliases:

       master family: master, dome, head
       slave  family: slave, body, base

   Ambiguous names (keywords from both families) return None.

3. **Integrity** — SHA-256 / MD5 of the COMPRESSED file (matches release
   sidecar conventions). Compared against ``image.sha256`` / ``.md5``
   when present, otherwise the digest is exposed for visual review.

All I/O here is synchronous; threading is the caller's responsibility
(WizardState fires the marker read in a daemon thread, FlashViewModel
runs the hash inside a QThread worker).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import lzma
import re
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional

from astromechos_imager.core.bootpartition import (
    BootPartitionLayout,
    find_first_fat32_partition,
)
from astromechos_imager.core.errors import (
    MalformedRoleMarkerError,
    MissingRoleMarkerError,
    RoleMismatchError,
    WrongProjectMarkerError,
)
from astromechos_imager.core.models import Role


ROLE_MARKER_PATH = "/astromech_role.json"
DEFAULT_MAX_DECOMPRESS_MB = 600  # bumped from 128 (2026-05-31) — Pi OS Trixie
# boot partition is 512 MB; 128 MB head truncated FAT32 metadata pyfatfs
# expected to read, causing "Read a different amount of data than was
# requested" on real Golden images (reproducible on slave but not master,
# which happened to keep all needed FAT structures in the first 128 MB
# after our Windows Format-Volume reconstruction). 600 MB safely covers
# the 512 MB FAT32 partition + the 4 MB pre-partition offset + margin.
EXPECTED_PROJECT = "AstromechOS"

# Audit Medium #33 / #34: hard caps on inputs that could otherwise OOM
# or recurse the JSON parser. The role marker is a ~100-byte file and
# sidecar checksums are 64-char hex + filename — these limits are
# orders of magnitude above the realistic max while still bounding any
# adversarial or accidentally-misnamed input.
MAX_MARKER_BYTES = 64 * 1024              # 64 KB plenty for a 3-key JSON
MAX_SIDECAR_BYTES = 8 * 1024              # 8 KB plenty for "<hex>  <file>"
MAX_JSON_DEPTH = 8                        # marker is flat — 8 is generous


# ── Filename hint ─────────────────────────────────────────────────────────

# Token aliases per role. The keyword must be delimited (start/end of
# basename or one of '-', '_', '.') so ``masterful-blueprint.img`` is
# NOT picked up as master.
_ROLE_KEYWORDS: dict[Role, tuple[str, ...]] = {
    Role.MASTER: ("master", "dome", "head"),
    Role.SLAVE:  ("slave",  "body", "base"),
}

# Use a lookbehind for the leading delimiter so it isn't consumed by the
# match — otherwise findall on "master_slave_combo.img" would only see
# "master" because the trailing "_" got eaten and is no longer available
# as the leading delimiter of "slave".
_KEYWORD_RE = re.compile(
    r"(?:^|(?<=[-_.]))("
    + "|".join(kw for kws in _ROLE_KEYWORDS.values() for kw in kws)
    + r")(?=[-_.]|$)",
    re.IGNORECASE,
)


def guess_role_from_filename(name_or_path: str) -> Role | None:
    """Return ``Role.MASTER`` / ``Role.SLAVE`` if the basename embeds
    exactly one family's keyword, else ``None`` (no match OR ambiguous)."""
    basename = Path(name_or_path).name.lower()
    matches = _KEYWORD_RE.findall(basename)
    if not matches:
        return None
    roles_found: set[Role] = set()
    for token in matches:
        for role, kws in _ROLE_KEYWORDS.items():
            if token in kws:
                roles_found.add(role)
                break
    if len(roles_found) != 1:
        return None
    return roles_found.pop()


# ── Strict marker validator (HARD BLOCK on any failure) ───────────────────


def _validate_marker_from_bp(
    bp,
    image_name: str,
    expected_role: Role,
) -> dict:
    """Read ``/astromech_role.json`` from a BootPartition-like object and
    validate it. Returns the parsed marker dict on success, raises the
    appropriate ``ImageRoleValidationError`` subclass otherwise.

    The BootPartition protocol used here is the read-only subset:
    ``bp.exists(path) -> bool`` and ``bp.read_bytes(path) -> bytes``.
    Both ``PyFatFsBootPartition`` (image-side) and ``DriveLetterBoot-
    Partition`` (post-flash readback) satisfy it.
    """
    if not bp.exists(ROLE_MARKER_PATH):
        raise MissingRoleMarkerError(image_name)

    raw = bp.read_bytes(ROLE_MARKER_PATH)

    # Audit Medium #34: cap the raw blob before JSON parsing. A
    # multi-megabyte "marker" is either a misnamed file or a deliberate
    # OOM attempt; in both cases reject early without feeding the parser.
    if len(raw) > MAX_MARKER_BYTES:
        raise MalformedRoleMarkerError(
            image_name,
            f"marker exceeds {MAX_MARKER_BYTES} bytes (got {len(raw)}) — "
            f"AstromechOS markers are <1 KB",
        )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise MalformedRoleMarkerError(image_name, "marker is not valid UTF-8")

    # Audit Medium #34: deeply nested JSON raises RecursionError, NOT
    # JSONDecodeError. Catch both so the strict "everything raises
    # MalformedRoleMarkerError" contract holds and the wizard's
    # missing-marker amber soft-pass does not swallow a parser bomb.
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedRoleMarkerError(image_name, f"invalid JSON: {exc.msg}")
    except (RecursionError, ValueError) as exc:
        raise MalformedRoleMarkerError(
            image_name, f"JSON parser failure ({type(exc).__name__}): {exc}"
        )

    if not isinstance(obj, dict):
        raise MalformedRoleMarkerError(
            image_name,
            f"expected JSON object at top level, got {type(obj).__name__}",
        )

    for required in ("role", "project", "version"):
        if required not in obj:
            raise MalformedRoleMarkerError(
                image_name, f"missing required key {required!r}"
            )

    raw_role = obj["role"]
    if not isinstance(raw_role, str):
        raise MalformedRoleMarkerError(image_name, "role must be a string")

    normalised = raw_role.strip().lower()
    if normalised not in ("master", "slave"):
        raise MalformedRoleMarkerError(
            image_name,
            f"unknown role {normalised!r} — expected 'master' or 'slave'",
        )

    if obj["project"] != EXPECTED_PROJECT:
        raise WrongProjectMarkerError(image_name, str(obj["project"]))

    found_role = Role.MASTER if normalised == "master" else Role.SLAVE
    if found_role != expected_role:
        raise RoleMismatchError(
            expected=expected_role.value,
            found=normalised,
            image_name=image_name,
        )

    return obj


# ── High-level helper: open image → mount FAT32 → delegate ────────────────


@contextmanager
def _decompressed_head_as_tempfile(path: Path, max_bytes: int) -> Iterator[Path]:
    """Stage the leading ``max_bytes`` of ``path`` into a temp file and
    yield its path. Handles .img / .img.xz / .img.gz / .zip transparently.

    The temp file is wide enough to host the MBR + FAT32 reserved region
    + root directory + a tiny file like ``astromech_role.json`` —
    typically ~10 MB into the partition, comfortably inside the default
    128 MB window. The temp file is unlinked on exit.
    """
    # Audit High #5 / #6: track both the outer ZipFile and the inner
    # opener so the zip handle is always closed (was leaked when an inner
    # .img was found), AND reject zips without any .img member instead
    # of silently re-reading the zip as raw bytes (which would mislead
    # the operator with "cannot parse MBR").
    name_lower = path.name.lower()
    zf: zipfile.ZipFile | None = None
    if name_lower.endswith(".xz"):
        opener: Callable = lambda: lzma.open(path, "rb")
    elif name_lower.endswith(".gz"):
        opener = lambda: gzip.open(path, "rb")
    elif name_lower.endswith(".zip"):
        zf = zipfile.ZipFile(path)
        inner = next(
            (n for n in zf.namelist() if n.lower().endswith(".img")),
            None,
        )
        if inner is None:
            zf.close()
            raise MalformedRoleMarkerError(
                path.name, "zip archive contains no .img member"
            )
        opener = lambda: zf.open(inner)
    else:
        opener = lambda: path.open("rb")

    with tempfile.NamedTemporaryFile(
        suffix=".img", delete=False, prefix="astromech_marker_"
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        src = opener()
        try:
            with open(tmp_path, "wb") as dst:
                remaining = max_bytes
                while remaining > 0:
                    chunk = src.read(min(remaining, 1 << 20))
                    if not chunk:
                        break
                    dst.write(chunk)
                    remaining -= len(chunk)
        finally:
            try:
                src.close()
            except Exception:
                pass
            # Audit High #5: close the outer ZipFile handle too.
            if zf is not None:
                try:
                    zf.close()
                except Exception:
                    pass
        yield tmp_path
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


class _ReadOnlyBootPartitionAdapter:
    """Read-only BootPartition subset wrapping a live PyFatFS handle."""

    def __init__(self, fs) -> None:
        self._fs = fs

    def exists(self, p: str) -> bool:
        return bool(self._fs.exists(p))

    def read_bytes(self, p: str) -> bytes:
        return self._fs.readbytes(p)


def validate_image_role(
    path: Path,
    expected_role: Role,
    max_decompress_mb: int = DEFAULT_MAX_DECOMPRESS_MB,
) -> dict:
    """Open an image file, mount its FAT32 boot partition, and validate
    the role marker against ``expected_role``.

    Raises the same exceptions as :func:`_validate_marker_from_bp`. The
    caller decides whether to surface them as hard blocks (Flash
    preflight) or as soft fallbacks (Wizard preview, per operator
    policy: missing marker → amber warning, others → red block).
    """
    from astromechos_imager.core.bootpartition import (
        _import_pyfatfs, BootPartitionMountError,
    )

    max_bytes = max_decompress_mb * 1024 * 1024
    with _decompressed_head_as_tempfile(path, max_bytes) as tmp_path:
        if tmp_path.stat().st_size < 512:
            # Audit Medium #28: a sub-512-byte image is corrupted /
            # truncated, not "marker absent". Use Malformed so the
            # wizard hard-blocks instead of soft-passing amber.
            raise MalformedRoleMarkerError(
                path.name,
                f"image is too small for an MBR "
                f"({tmp_path.stat().st_size} bytes, expected ≥ 512)",
            )

        with open(tmp_path, "rb") as f:
            mbr = f.read(512)
        # Audit Medium #35: narrow the catch to the specific MBR-parse
        # error so library bugs (e.g. unexpected struct alignment) don't
        # masquerade as "re-extract the image" advice in the recovery
        # hint. BootPartitionMountError is the only thing
        # find_first_fat32_partition is contracted to raise.
        try:
            layout: BootPartitionLayout = find_first_fat32_partition(mbr)
        except BootPartitionMountError as exc:
            raise MalformedRoleMarkerError(
                path.name, f"cannot locate FAT32 partition in MBR: {exc}"
            )

        PyFatFS = _import_pyfatfs()
        try:
            fs = PyFatFS(filename=str(tmp_path), offset=layout.offset)
        except Exception as exc:  # pyfatfs has no single exported error class
            raise MalformedRoleMarkerError(
                path.name, f"cannot mount FAT32 partition: {exc}"
            )
        try:
            return _validate_marker_from_bp(
                _ReadOnlyBootPartitionAdapter(fs), path.name, expected_role
            )
        finally:
            try:
                fs.close()
            except Exception:
                pass


# ── Sidecar checksum discovery ────────────────────────────────────────────


_HASH_RE = {
    "sha256": re.compile(r"^[0-9a-fA-F]{64}$"),
    "md5":    re.compile(r"^[0-9a-fA-F]{32}$"),
}


def find_sidecar_checksum(image_path: Path) -> tuple[str, str] | None:
    """Look for a checksum file next to ``image_path``.

    Tries (in order) ``image.sha256``, ``image.SHA256``, ``image.sha256sum``,
    same for md5. Accepts both bare ``<hex>`` content and coreutils
    ``<hex>  <filename>``. Returns ``(algo, hex_lower)`` or None.
    """
    base = image_path.name
    candidates: list[tuple[Path, str]] = []
    for algo in ("sha256", "md5"):
        for ext in (algo, algo.upper(), f"{algo}sum"):
            candidates.append((image_path.parent / f"{base}.{ext}", algo))
    for path, algo in candidates:
        if not path.is_file():
            continue
        # Audit Medium #33: read at most MAX_SIDECAR_BYTES so a multi-GB
        # misnamed sidecar can't OOM the process. Decode with utf-8-sig
        # to swallow a PowerShell-emitted BOM (otherwise a legitimate
        # sidecar would silently fail the regex).
        try:
            with path.open("rb") as f:
                blob = f.read(MAX_SIDECAR_BYTES + 1)
        except OSError:
            continue
        if len(blob) > MAX_SIDECAR_BYTES:
            continue   # too large to be a real coreutils sidecar
        try:
            text = blob.decode("utf-8-sig", errors="replace").strip()
        except (UnicodeDecodeError, LookupError):
            continue
        if not text:
            continue
        first = text.split()[0]
        if _HASH_RE[algo].fullmatch(first):
            return (algo, first.lower())
    return None


# ── Streaming hash (compressed-as-downloaded) ─────────────────────────────


class HashCancelled(InterruptedError):
    """Raised when ``cancel_event`` fires mid-hash."""


def hash_compressed_file(
    path: Path,
    algo: str = "sha256",
    chunk_size: int = 1 << 20,
    progress_cb: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Stream ``path`` through ``hashlib`` and return the hex digest.

    Operates on the file AS-IS (compressed when the source is
    .xz/.gz/.zip) so the result matches the sidecar conventions used by
    Raspberry Pi / Ubuntu / Debian releases.
    """
    h = hashlib.new(algo)
    total = max(1, path.stat().st_size)
    done = 0
    with path.open("rb") as f:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise HashCancelled("hash cancelled by caller")
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            if progress_cb is not None:
                progress_cb(min(1.0, done / total))
    return h.hexdigest()
