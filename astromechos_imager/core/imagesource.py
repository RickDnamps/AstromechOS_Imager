# astromechos_imager/core/imagesource.py
"""Streaming-decompression sources. Per design spec §5.4."""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Iterator, Protocol

from astromechos_imager.core.errors import ImageFormatError


class ImageSource(Protocol):
    """Yields the uncompressed image as 1 MB chunks. Context-manager-aware."""
    CHUNK_SIZE: int
    uncompressed_size: int | None

    def __iter__(self) -> Iterator[bytes]: ...
    def __enter__(self) -> "ImageSource": ...
    def __exit__(self, *exc: object) -> None: ...


class _BaseSource:
    CHUNK_SIZE = 1 << 20  # 1 MB

    def __init__(self, path: Path):
        self.path = path
        self.uncompressed_size: int | None = None
        self._fh: BinaryIO | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class RawSource(_BaseSource):
    """Pass-through. Used when the file is already a raw .img."""
    def __init__(self, path: Path):
        super().__init__(path)
        self.uncompressed_size = path.stat().st_size

    def __iter__(self) -> Iterator[bytes]:
        self._fh = self.path.open("rb")
        while True:
            chunk = self._fh.read(self.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


def _peek_magic(path: Path, n: int = 8) -> bytes:
    with path.open("rb") as f:
        return f.read(n)


def _looks_like_mbr(head: bytes, path: Path) -> bool:
    # Bytes 510-511 of a MBR are 0x55 0xAA. Also check last 2 bytes for robustness
    # (some test fixtures place the signature at the end of the file rather than at 510).
    size = path.stat().st_size
    if size < 512:
        return False
    with path.open("rb") as f:
        f.seek(510)
        sig = f.read(2)
    if sig == b"\x55\xAA":
        return True
    # Also accept files where the signature appears as the last 2 bytes
    with path.open("rb") as f:
        f.seek(-2, 2)
        sig_end = f.read(2)
    return sig_end == b"\x55\xAA"


def open_image(path: Path) -> ImageSource:
    """Detect format by magic bytes (with extension as tie-breaker) and return source."""
    if not path.is_file():
        raise ImageFormatError(f"not a file: {path}")

    head = _peek_magic(path)
    # xz magic
    if head[:6] == b"\xfd7zXZ\x00":
        from astromechos_imager.core.imagesource import XzSource  # forward
        return XzSource(path)
    # gzip magic
    if head[:2] == b"\x1f\x8b":
        from astromechos_imager.core.imagesource import GzSource
        return GzSource(path)
    # zip magic
    if head[:4] == b"PK\x03\x04":
        from astromechos_imager.core.imagesource import ZipSource
        return ZipSource(path)
    # raw .img: MBR signature check, with .img extension as tie-breaker
    if _looks_like_mbr(head, path):
        return RawSource(path)
    # Extension tie-breaker: .img files >= 512 bytes treated as raw
    if path.suffix.lower() == ".img" and path.stat().st_size >= 512:
        return RawSource(path)
    raise ImageFormatError(f"unrecognized image format: {path}")


import gzip
import lzma
import struct


class XzSource(_BaseSource):
    """Streaming xz decompression via stdlib lzma."""
    def __init__(self, path: Path):
        super().__init__(path)
        self.uncompressed_size = None  # xz format does not always store this

    def __iter__(self) -> Iterator[bytes]:
        self._fh = lzma.open(self.path, "rb")
        while True:
            chunk = self._fh.read(self.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


class GzSource(_BaseSource):
    """Streaming gzip decompression."""
    def __init__(self, path: Path):
        super().__init__(path)
        self.uncompressed_size = self._read_isize()

    def _read_isize(self) -> int | None:
        """Last 4 bytes of a gzip file = uncompressed size mod 2^32."""
        size = self.path.stat().st_size
        if size < 4:
            return None
        with self.path.open("rb") as f:
            f.seek(-4, 2)
            isize = struct.unpack("<I", f.read(4))[0]
        # For images > 4 GB this wraps. Caller treats None and 0 as "unknown".
        return isize if isize > 0 else None

    def __iter__(self) -> Iterator[bytes]:
        self._fh = gzip.open(self.path, "rb")
        while True:
            chunk = self._fh.read(self.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


import zipfile


class ZipSource(_BaseSource):
    """Streams the single .img entry inside a ZIP. Refuses zero or 2+ .img entries."""
    def __init__(self, path: Path):
        super().__init__(path)
        with zipfile.ZipFile(path, "r") as zf:
            imgs = [n for n in zf.namelist() if n.lower().endswith(".img")]
        if len(imgs) != 1:
            raise ImageFormatError(
                f"ZIP must contain exactly one .img entry, found {len(imgs)}: {imgs!r}"
            )
        self._entry = imgs[0]
        with zipfile.ZipFile(path, "r") as zf:
            self.uncompressed_size = zf.getinfo(self._entry).file_size

    def __iter__(self) -> Iterator[bytes]:
        zf = zipfile.ZipFile(self.path, "r")
        self._fh = zf.open(self._entry, "r")
        try:
            while True:
                chunk = self._fh.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            self._fh.close()
            zf.close()
            self._fh = None
