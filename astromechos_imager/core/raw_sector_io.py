"""RawSectorFile — a seekable file-like view of one partition on a raw device.

This is the keystone of the "userspace FAT, never mount" customize path
(the fix for the Windows "Format K:?" pop-up). It wraps a sector-addressed
raw device (``\\.\PHYSICALDRIVEn``) and presents a normal Python file
object windowed to ``[part_start, part_start + part_len)``, with a
read-modify-write 512-byte sector cache so an arbitrary-offset small write
(a 32-byte FAT directory entry at byte 12345, say) lands correctly even
though the underlying device only accepts sector-aligned I/O.

Fed to ``pyfatfs.PyFat.set_fp``, it lets us read and write files inside the
FAT32 boot partition WITHOUT asking Windows to mount the volume — which is
exactly how rpi-imager's DeviceWrapper avoids the shell pop-up. No mount,
no drive letter, no Explorer, no "Format K:?" dialog.

The underlying ``raw_device`` must expose:
    read(offset: int, length: int) -> bytes      # sector-aligned
    write(offset: int, data: bytes) -> int        # sector-aligned
    flush() -> None
which is satisfied by ``platform.windows._Win32RawDevice`` and the test
fakes. Offsets passed to it are absolute device byte offsets.
"""
from __future__ import annotations


class RawSectorFile:
    """Sector-cached, windowed, seekable file-like over a raw block device."""

    SECTOR = 512

    def __init__(self, raw_device, part_start: int, part_len: int):
        if part_start % self.SECTOR != 0:
            raise ValueError(f"part_start {part_start} not sector-aligned")
        self._dev = raw_device
        self._base = part_start
        self._size = part_len
        self._pos = 0
        self._cache: dict[int, bytearray] = {}   # sector index -> 512 bytes
        self._dirty: set[int] = set()
        self._closed = False

    # ── file-object protocol pyfatfs checks ──────────────────────────
    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, pos: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = pos
        elif whence == 1:
            self._pos += pos
        elif whence == 2:
            self._pos = self._size + pos
        else:
            raise ValueError(f"invalid whence {whence}")
        return self._pos

    def tell(self) -> int:
        return self._pos

    # ── sector cache (read-modify-write) ─────────────────────────────
    def _sector(self, idx: int) -> bytearray:
        buf = self._cache.get(idx)
        if buf is None:
            raw = self._dev.read(self._base + idx * self.SECTOR, self.SECTOR)
            buf = bytearray(raw.ljust(self.SECTOR, b"\x00"))
            self._cache[idx] = buf
        return buf

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self._size - self._pos
        out = bytearray()
        remaining = n
        while remaining > 0 and self._pos < self._size:
            idx, off = divmod(self._pos, self.SECTOR)
            take = min(self.SECTOR - off, remaining, self._size - self._pos)
            buf = self._sector(idx)
            out += buf[off:off + take]
            self._pos += take
            remaining -= take
        return bytes(out)

    def write(self, b) -> int:
        data = bytes(b)
        total = len(data)
        done = 0
        while done < total:
            idx, off = divmod(self._pos, self.SECTOR)
            take = min(self.SECTOR - off, total - done)
            buf = self._sector(idx)                 # read-modify-write
            buf[off:off + take] = data[done:done + take]
            self._dirty.add(idx)
            self._pos += take
            done += take
        return total

    def flush(self) -> None:
        for idx in sorted(self._dirty):
            self._dev.write(self._base + idx * self.SECTOR,
                            bytes(self._cache[idx]))
        try:
            self._dev.flush()
        except Exception:
            pass
        self._dirty.clear()

    def close(self) -> None:
        if self._closed:
            return
        self.flush()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed
