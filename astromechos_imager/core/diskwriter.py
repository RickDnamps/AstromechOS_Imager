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
from collections.abc import Callable
from dataclasses import dataclass

from astromechos_imager.core.errors import HashMismatchError, WriteError
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
                # Deliver the end-of-stream sentinel so the consumer's
                # blocking q.get() unblocks. Use a BLOCKING put with a
                # cancel-aware timeout loop — NEVER drop a queued chunk to
                # make room.
                #
                # The previous ``q.get_nowait()`` drop-to-fit was a real
                # data-loss + length bug: on a SLOW device (an SD card at
                # ~10 MB/s vs near-instant decompression) the consumer
                # always lags, so the queue is FULL when the producer
                # finishes — and the drop silently discarded the last
                # data chunk that had ALREADY been folded into
                # ``source_sha256``. Result: the device was 1 chunk
                # (~1 MB) short, ``bytes_written`` undercounted by the
                # same amount, and verify_readback compared a 1-MB-short
                # readback against the full-image hash → a deterministic
                # SHA-256 mismatch on every large flash. (It never bit on
                # fast targets, where the queue drains before finish.)
                #
                # In the normal path the consumer keeps draining until it
                # sees the sentinel, so the blocking put always succeeds
                # within a slot's time. On CANCEL the consumer may have
                # already stopped draining; there we DO discard from the
                # queue to avoid deadlocking the join (the data is being
                # abandoned anyway).
                while True:
                    try:
                        q.put(None, timeout=0.5)
                        break
                    except queue.Full:
                        if self.cancel.is_set():
                            try:
                                q.get_nowait()
                            except queue.Empty:
                                pass
                        # else: consumer is alive and draining — retry.

        # Prefer the compressed-stream position when the source exposes
        # it — that's always 0..100% of a known fixed total (the .gz
        # file size on disk). For sources without it (raw .img, .xz,
        # .zip), fall back to the decompressed byte offset and rely on
        # ``source.uncompressed_size``. Gzip's ``ISIZE`` field is
        # ``uncompressed_size mod 2^32`` so for Pi-OS-sized images
        # (~5.7 GB) it wraps to ~1.7 GB — the UI used to render that
        # as "320 %" before this switch.
        use_compressed_progress = (
            callable(getattr(self.source, "compressed_position", None))
            and getattr(self.source, "compressed_size", None) is not None
        )

        def _progress_pair() -> tuple[int, int | None]:
            if use_compressed_progress:
                return (self.source.compressed_position(),
                        self.source.compressed_size)  # type: ignore[attr-defined]
            return (consumer_total[0], self.source.uncompressed_size)

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
                        done, total = _progress_pair()
                        self.on_progress(DiskWriterProgress(
                            phase="decompress_write",
                            bytes_done=done,
                            bytes_total=total,
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
                    done, total = _progress_pair()
                    self.on_progress(DiskWriterProgress(
                        phase="decompress_write",
                        bytes_done=done,
                        bytes_total=total,
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
