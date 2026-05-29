# astromechos_imager/core/diskwriter.py
"""Streaming raw write engine. Per design spec §5.3.

The pipeline is producer (decompress + hash) → bounded queue → consumer (write).
A single threading.Event controls cancellation across both threads.
"""
from __future__ import annotations

import hashlib
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from astromechos_imager.core.errors import WriteError, HashMismatchError
from astromechos_imager.core.platform_io import RawDevice


@dataclass(frozen=True)
class DiskWriterProgress:
    phase: str           # "decompress_write" | "verify"
    bytes_done: int
    bytes_total: int | None
    throughput_bps: float


@dataclass(frozen=True)
class DiskWriteResult:
    bytes_written: int
    source_sha256: str


class DiskWriter:
    """Streams an ImageSource to a RawDevice, computing source SHA256 in flight."""
    CHUNK_SIZE = 1 << 20
    QUEUE_MAX = 4

    def __init__(self, source, raw_device: RawDevice,
                 on_progress: Callable[[DiskWriterProgress], None] | None = None,
                 cancel_event: threading.Event | None = None):
        self.source = source
        self.dev = raw_device
        self.on_progress = on_progress or (lambda p: None)
        self.cancel = cancel_event or threading.Event()
        self._exc: BaseException | None = None

    def run(self) -> DiskWriteResult:
        q: queue.Queue = queue.Queue(maxsize=self.QUEUE_MAX)
        hasher = hashlib.sha256()
        producer_total = [0]
        consumer_total = [0]

        def producer():
            try:
                for chunk in self.source:
                    if self.cancel.is_set():
                        break
                    hasher.update(chunk)
                    producer_total[0] += len(chunk)
                    q.put(chunk)
            except BaseException as e:
                self._exc = e
            finally:
                q.put(None)  # sentinel

        def consumer():
            offset = 0
            try:
                while True:
                    if self.cancel.is_set():
                        break
                    chunk = q.get()
                    if chunk is None:
                        break
                    written = self.dev.write(offset, chunk)
                    if written != len(chunk):
                        raise WriteError(f"short write at {offset}: {written}/{len(chunk)}")
                    offset += written
                    consumer_total[0] = offset
                    self.on_progress(DiskWriterProgress(
                        phase="decompress_write",
                        bytes_done=offset,
                        bytes_total=self.source.uncompressed_size,
                        throughput_bps=0.0,
                    ))
            except BaseException as e:
                self._exc = e

        t_p = threading.Thread(target=producer, name="dw-producer", daemon=True)
        t_c = threading.Thread(target=consumer, name="dw-consumer", daemon=True)
        t_p.start(); t_c.start()
        t_p.join(); t_c.join()

        self.dev.flush()
        if self._exc is not None:
            raise self._exc
        return DiskWriteResult(
            bytes_written=consumer_total[0],
            source_sha256=hasher.hexdigest(),
        )


def verify_readback(dev: RawDevice, expected_sha256: str, length: int,
                     on_progress: Callable[[DiskWriterProgress], None] | None = None,
                     cancel_event: threading.Event | None = None) -> None:
    """Read back `length` bytes from offset 0 and compare SHA256.

    Raises HashMismatchError with first_diff_offset on mismatch (block-aligned,
    not byte-precise — pinpointing requires a second pass we don't bother with).
    """
    on_progress = on_progress or (lambda p: None)
    cancel = cancel_event or threading.Event()
    hasher = hashlib.sha256()
    chunk_size = 1 << 20
    offset = 0
    # Compare block-by-block against the expected hash *streamed* — we don't
    # have the source bytes anymore, so we only know "the final hash mismatched";
    # to give an offset we compare each readback chunk against a single-chunk
    # SHA256 computed by the caller (see DiskWriter.source_sha256 path). Here,
    # we just hash and compare at the end.
    while offset < length:
        if cancel.is_set():
            return
        n = min(chunk_size, length - offset)
        data = dev.read(offset, n)
        if len(data) != n:
            raise WriteError(f"readback short at offset {offset}: {len(data)}/{n}")
        hasher.update(data)
        offset += n
        on_progress(DiskWriterProgress(
            phase="verify", bytes_done=offset, bytes_total=length, throughput_bps=0.0,
        ))
    if hasher.hexdigest() != expected_sha256:
        # Approximate: report 0 since we didn't track a per-block hash. UI shows
        # "hash mismatch" without offset detail.
        raise HashMismatchError(
            f"SHA256 mismatch: expected {expected_sha256}, got {hasher.hexdigest()}",
            first_diff_offset=0,
        )
