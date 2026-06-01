"""5-second isolation of the bytes_written accounting bug.

Run the production DiskWriter on the SMALL fixture gz against a plain temp
FILE (no SD), and compare:
  - DiskWriteResult.bytes_written
  - len(first_block_data)
  - the true decompressed image length
  - what's actually on the temp file [1MB:] vs source[1MB:]

If bytes_written == decompressed_len -> accounting OK (bug is elsewhere).
If bytes_written == decompressed_len - first_block -> the deferred block
isn't counted, and verify_readback reads 1 MB short -> deterministic hash
mismatch (the real bug, NOT a USB bridge).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import os
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.core.diskwriter import DiskWriter, verify_readback
from astromechos_imager.core.imagesource import open_image

GZ = Path(r"tests\fixtures\pi_os_shaped.img.gz")


import time as _time

class FileDevice:
    """Minimal RawDevice over a regular file (sparse-capable).

    ``slow`` adds a per-write delay to make the consumer lag behind the
    decompressing producer — reproducing the queue-full-at-finish state
    that a real (slow) SD card always hits.
    """
    sector_size = 512

    def __init__(self, path, slow=0.0):
        self._f = open(path, "r+b")
        self._slow = slow

    def write(self, offset, data):
        if self._slow:
            _time.sleep(self._slow)
        self._f.seek(offset)
        self._f.write(data)
        return len(data)

    def read(self, offset, length):
        self._f.seek(offset)
        d = self._f.read(length)
        return d if len(d) == length else d + b"\x00" * (length - len(d))

    def flush(self):
        self._f.flush()

    def close(self):
        self._f.close()


def main() -> int:
    # true decompressed length
    true_len = 0
    with gzip.open(GZ, "rb") as f:
        while True:
            c = f.read(1 << 20)
            if not c:
                break
            true_len += len(c)
    print(f"true decompressed length : {true_len}")

    tmp = Path(tempfile.gettempdir()) / "astro_bw_test.img"
    if tmp.exists():
        tmp.unlink()
    # pre-size the file so writes at offset land
    with open(tmp, "wb") as f:
        f.truncate(true_len + (1 << 20))

    # slow=0.02s/MB -> consumer lags the decompressor, queue stays full,
    # reproducing the real SD card's producer/consumer timing.
    dev = FileDevice(tmp, slow=float(os.environ.get("SLOW", "0.02")))
    try:
        with open_image(GZ) as src:
            wr = DiskWriter(src, dev).run()
        # write the deferred first block too (so the file is complete)
        if wr.first_block_data:
            dev.write(0, wr.first_block_data)
        dev.flush()
    finally:
        dev.close()

    fb = len(wr.first_block_data) if wr.first_block_data else 0
    print(f"first_block_data length  : {fb}")
    print(f"bytes_written            : {wr.bytes_written}")
    print(f"source_sha256            : {wr.source_sha256[:16]}...")
    print(f"\ntrue_len - bytes_written : {true_len - wr.bytes_written}  "
          f"(== first_block? {true_len - wr.bytes_written == fb})")

    # Re-run verify_readback the way the orchestrator does, against the file,
    # with length=bytes_written (current) and length=true_len (candidate fix).
    devr = FileDevice(tmp)
    try:
        def try_len(length, label):
            try:
                verify_readback(devr, wr.source_sha256, length,
                                first_block=wr.first_block_data)
                print(f"  {label} length={length}: ✅ MATCH")
            except Exception as e:
                print(f"  {label} length={length}: ❌ {type(e).__name__}: {str(e)[:60]}")
        print("\nverify_readback:")
        try_len(wr.bytes_written, "bytes_written")
        try_len(true_len, "true_len     ")
    finally:
        devr.close()
        tmp.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
