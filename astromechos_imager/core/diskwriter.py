# astromechos_imager/core/diskwriter.py
"""Streaming raw write engine. Per design spec §5.3.

The pipeline is producer (decompress + hash) → bounded queue → consumer (write).
A single threading.Event controls cancellation across both threads.
"""
from __future__ import annotations

import hashlib
import queue
import threading
import time
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
    #: First chunk of the source that was deliberately NOT written to the
    #: device — Windows would otherwise auto-mount the freshly-written FAT32
    #: partition mid-flash and inject ``System Volume Information`` bytes,
    #: corrupting the verify_readback comparison (audit Bug #0). Carries the
    #: bytes of the MBR / boot sector / first 1 MB, hashed in-flight so the
    #: source SHA256 is unaffected. Callers (orchestrator) write this back
    #: to offset 0 AFTER verify_readback succeeds, completing the partition
    #: table the kernel needs to mount the new filesystem.
    #:
    #: ``None`` when the source was shorter than one ``CHUNK_SIZE`` and the
    #: caller-supplied feature was not exercised — degenerate edge case
    #: not seen in production (Pi OS images are always > 1 MB).
    first_block_data: bytes | None = None


class DiskWriter:
    """Streams an ImageSource to a RawDevice, computing source SHA256 in flight.

    Implements the "deferred first block" technique from rpi-imager
    (``rpi-imager/src/downloadthread.cpp::_writeFile`` first-block branch
    + ``_verify``): the very first chunk of the source — which contains
    the MBR with the partition table — is hashed in-flight but NOT
    written to the device during the streaming phase. The caller writes
    it back at offset 0 only after ``verify_readback`` succeeds. Until
    that final write happens, Windows sees an invalid partition table
    and refuses to auto-mount the new FAT32 partition, eliminating the
    race that corrupted our readback hashes in the E2E audit (Bug #0).
    """
    CHUNK_SIZE = 1 << 20
    QUEUE_MAX = 4

    def __init__(self, source, raw_device: RawDevice,
                 on_progress: Callable[[DiskWriterProgress], None] | None = None,
                 cancel_event: threading.Event | None = None,
                 defer_first_block: bool = True):
        self.source = source
        self.dev = raw_device
        self.on_progress = on_progress or (lambda p: None)
        self.cancel = cancel_event or threading.Event()
        self.defer_first_block = defer_first_block
        self._exc: BaseException | None = None

    def run(self) -> DiskWriteResult:
        q: queue.Queue = queue.Queue(maxsize=self.QUEUE_MAX)
        hasher = hashlib.sha256()
        producer_total = [0]
        consumer_total = [0]
        # Deferred first block (see DiskWriteResult.first_block_data).
        # Consumer fills this with the bytes of the first chunk it
        # receives, then SKIPS writing them to the device and advances
        # its offset by len(first_block) so subsequent chunks land at
        # their correct disk offsets.
        first_block_box: list[bytes | None] = [None]

        def producer():
            try:
                for chunk in self.source:
                    if self.cancel.is_set():
                        break
                    hasher.update(chunk)
                    producer_total[0] += len(chunk)
                    # Audit Medium #31: use a timeout-based put so the
                    # producer wakes up periodically to re-check the
                    # cancel flag, even if the consumer died and stopped
                    # draining the queue. Without this, q.put(chunk) on
                    # a full queue would block forever and t_p.join()
                    # would hang the run() call.
                    while not self.cancel.is_set():
                        try:
                            q.put(chunk, timeout=0.5)
                            break
                        except queue.Full:
                            continue
            except BaseException as e:
                self._exc = e
            finally:
                # Always drop the sentinel even on cancel so the
                # consumer's q.get() unblocks.
                try:
                    q.put_nowait(None)
                except queue.Full:
                    # Consumer is alive but queue is full; drain one and
                    # retry once. If still full the consumer crashed and
                    # we leak the sentinel — acceptable, the queue dies
                    # with this thread.
                    try:
                        q.get_nowait()
                        q.put_nowait(None)
                    except (queue.Empty, queue.Full):
                        pass

        def consumer():
            offset = 0
            saw_first = False
            # Rolling-window throughput sampler. We snapshot (wall_clock,
            # bytes_done) at consumer entry, then recompute the rate every
            # ``_THROUGHPUT_WINDOW_S`` seconds. Reporting the instantaneous
            # bytes/sec of each 1 MB chunk would alias on USB stalls and
            # make the UI badge jitter; a 1 s window smooths that.
            _THROUGHPUT_WINDOW_S = 1.0
            window_t0 = time.monotonic()
            window_b0 = 0
            last_throughput_bps = 0.0
            try:
                while True:
                    if self.cancel.is_set():
                        break
                    chunk = q.get()
                    if chunk is None:
                        break
                    if self.defer_first_block and not saw_first:
                        # Buffer the first chunk (contains MBR + boot
                        # sector). DO NOT write to disk — orchestrator
                        # writes it back after verify_readback succeeds.
                        first_block_box[0] = bytes(chunk)  # detach from queue buffer
                        offset += len(chunk)
                        consumer_total[0] = offset
                        saw_first = True
                        # Reset the throughput window now that we've
                        # absorbed the deferred first block — its 1 MB
                        # didn't actually hit the device so it would
                        # massively inflate the first sample.
                        window_t0 = time.monotonic()
                        window_b0 = offset
                        self.on_progress(DiskWriterProgress(
                            phase="decompress_write",
                            bytes_done=offset,
                            bytes_total=self.source.uncompressed_size,
                            throughput_bps=0.0,
                        ))
                        continue
                    written = self.dev.write(offset, chunk)
                    if written != len(chunk):
                        raise WriteError(f"short write at {offset}: {written}/{len(chunk)}")
                    offset += written
                    consumer_total[0] = offset
                    now = time.monotonic()
                    elapsed = now - window_t0
                    if elapsed >= _THROUGHPUT_WINDOW_S:
                        delta_bytes = offset - window_b0
                        if elapsed > 0 and delta_bytes >= 0:
                            last_throughput_bps = delta_bytes / elapsed
                        window_t0 = now
                        window_b0 = offset
                    self.on_progress(DiskWriterProgress(
                        phase="decompress_write",
                        bytes_done=offset,
                        bytes_total=self.source.uncompressed_size,
                        throughput_bps=last_throughput_bps,
                    ))
            except BaseException as e:
                self._exc = e
                # Audit Medium #31: if the consumer dies, set cancel so
                # the producer unblocks at its next iteration instead of
                # filling the queue forever.
                self.cancel.set()

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
            first_block_data=first_block_box[0],
        )


def verify_readback(dev: RawDevice, expected_sha256: str, length: int,
                     on_progress: Callable[[DiskWriterProgress], None] | None = None,
                     cancel_event: threading.Event | None = None,
                     first_block: bytes | None = None) -> None:
    """Read back `length` bytes and compare SHA256 to ``expected_sha256``.

    When ``first_block`` is provided, the function:
      - hashes ``first_block`` into the verify hash via ``hasher.update``;
      - starts the disk read from offset ``len(first_block)`` (skipping
        the region the orchestrator has deliberately NOT written yet —
        the MBR region kept off-disk to prevent Windows auto-mount during
        the write/verify window — see ``DiskWriter`` docstring and
        audit Bug #0).

    When ``first_block`` is ``None`` the function reads the full range
    from offset 0 (legacy behaviour for callers that don't use the
    deferred-first-block path — image-to-image tests, fakes, callers
    that disable ``DiskWriter.defer_first_block``).

    Raises ``HashMismatchError`` if the computed hash doesn't match.
    """
    on_progress = on_progress or (lambda p: None)
    cancel = cancel_event or threading.Event()
    hasher = hashlib.sha256()
    chunk_size = 1 << 20

    # Rolling-window throughput sampler (see DiskWriter.run consumer for
    # the rationale — instantaneous bytes/sec jitters too much on USB
    # stalls; a 1 s averaging window gives the UI a stable badge value).
    _THROUGHPUT_WINDOW_S = 1.0
    last_throughput_bps = 0.0

    if first_block is not None:
        # Hash-inject the deferred first block — its bytes ARE part of
        # the source image's SHA256, but they are NOT on disk yet.
        hasher.update(first_block)
        offset = len(first_block)
        on_progress(DiskWriterProgress(
            phase="verify", bytes_done=offset, bytes_total=length, throughput_bps=0.0,
        ))
    else:
        offset = 0

    window_t0 = time.monotonic()
    window_b0 = offset

    while offset < length:
        if cancel.is_set():
            return
        n = min(chunk_size, length - offset)
        data = dev.read(offset, n)
        if len(data) != n:
            raise WriteError(f"readback short at offset {offset}: {len(data)}/{n}")
        hasher.update(data)
        offset += n
        now = time.monotonic()
        elapsed = now - window_t0
        if elapsed >= _THROUGHPUT_WINDOW_S:
            delta_bytes = offset - window_b0
            if elapsed > 0 and delta_bytes >= 0:
                last_throughput_bps = delta_bytes / elapsed
            window_t0 = now
            window_b0 = offset
        on_progress(DiskWriterProgress(
            phase="verify", bytes_done=offset, bytes_total=length,
            throughput_bps=last_throughput_bps,
        ))
    if hasher.hexdigest() != expected_sha256:
        # Approximate: report 0 since we didn't track a per-block hash. UI shows
        # "hash mismatch" without offset detail.
        raise HashMismatchError(
            f"SHA256 mismatch: expected {expected_sha256}, got {hasher.hexdigest()}",
            first_diff_offset=0,
        )
