"""Regression: handle close paths must be strictly idempotent + recycle-safe.

Errno 6 (ERROR_INVALID_HANDLE) and a latent Errno 5 (ERROR_ACCESS_DENIED on
a recycled live handle) came from double-closing the same handle value —
the orchestrator's finally racing a pyfatfs GC finalizer. These tests pin
the contract: every close() reaches CloseHandle at most once per handle,
and a None / INVALID_HANDLE_VALUE / 0 handle never reaches Win32 at all.
"""
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


class _FakeKernel:
    def __init__(self):
        self.closed: list[int] = []

    def CloseHandle(self, h):
        self.closed.append(h)
        return 1


def test_open_raw_device_raises_on_failed_createfilew(monkeypatch):
    """Regression: a FAILED CreateFileW returns (HANDLE)-1, which ctypes
    surfaces as 0xFFFFFFFFFFFFFFFF (NOT -1). open_raw_device MUST detect that
    and raise — otherwise the bogus handle reaches SetFilePointerEx and the
    field-observed `SetFilePointerEx FAILED ... err=6` appears BEFORE any
    byte is written. Pins the INVALID_HANDLE_VALUE sentinel fix."""
    from astromechos_imager.platform import windows as W

    class _FailingKernel(_FakeKernel):
        def CreateFileW(self, *a, **k):
            return W.INVALID_HANDLE_VALUE  # the unsigned (HANDLE)-1

    monkeypatch.setattr(W, "kernel32", lambda: _FailingKernel())
    monkeypatch.setattr(W.ctypes, "get_last_error", lambda: 5)
    with pytest.raises(OSError) as ei:
        W.open_raw_device(8)
    assert "CreateFileW" in str(ei.value)


def test_close_handle_skips_invalid_sentinels(monkeypatch):
    from astromechos_imager.platform import windows as W
    fk = _FakeKernel()
    monkeypatch.setattr(W, "kernel32", lambda: fk)

    W.close_handle(None)
    W.close_handle(W.INVALID_HANDLE_VALUE)
    W.close_handle(0)
    assert fk.closed == []          # none of these reach CloseHandle

    W.close_handle(1234)
    assert fk.closed == [1234]      # a real handle does


def test_win32_raw_device_double_close_is_idempotent(monkeypatch):
    from astromechos_imager.platform import windows as W
    fk = _FakeKernel()
    monkeypatch.setattr(W, "kernel32", lambda: fk)

    dev = W._Win32RawDevice(handle=4242, size_bytes=0)
    dev.close()
    dev.close()                     # second close must be a no-op
    dev.close()
    assert fk.closed == [4242]      # CloseHandle hit exactly once

    # flush after close never raises and never touches Win32
    dev.flush()
    assert fk.closed == [4242]

    # read/write after close raise a clear closed-handle error (errno 6)
    with pytest.raises(OSError) as ei:
        dev.write(0, b"x")
    assert ei.value.errno == 6


def test_plain_raw_device_double_close_is_idempotent(monkeypatch):
    from astromechos_imager.platform import windows as W
    fk = _FakeKernel()
    monkeypatch.setattr(W, "kernel32", lambda: fk)

    dev = W._PlainRawDevice.__new__(W._PlainRawDevice)  # skip CreateFileW
    dev._h = 7777
    dev.close()
    dev.close()
    assert fk.closed == [7777]
    dev.flush()                     # no-op, no raise
    assert fk.closed == [7777]


def test_raw_fat_boot_partition_double_close_is_idempotent():
    from astromechos_imager.core.raw_fat_partition import RawFatBootPartition

    class _Spy:
        def __init__(self):
            self.n = 0
        def close(self):
            self.n += 1
        def flush(self):
            pass

    bp = RawFatBootPartition.__new__(RawFatBootPartition)
    pfs, dev = _Spy(), _Spy()
    bp._pfs = pfs
    bp._device = dev
    bp._owns_device = True

    class _RawFile:
        _closed = False
    bp._raw_file = _RawFile()
    bp._closed = False

    bp.close()
    bp.close()
    bp.close()
    assert pfs.n == 1               # PyFatFS.close ran exactly once
    assert dev.n == 1               # owned device closed exactly once
    assert bp._raw_file._closed is True
