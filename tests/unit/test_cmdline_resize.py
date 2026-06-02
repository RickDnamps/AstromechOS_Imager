"""Unit tests for the FAT cmdline.txt rootfs auto-resize injection."""
from __future__ import annotations

import pytest

from astromechos_imager.core.cmdline_resize import (
    RESIZE_INIT_ARG,
    ensure_resize_init_in_cmdline,
    inject_resize_arg,
)
from astromechos_imager.core.errors import CmdlineInjectionFailedError

STOCK = b"console=tty1 root=PARTUUID=6c586e13-02 rootfstype=ext4 rootwait quiet\n"


def test_appends_when_absent():
    out = ensure_resize_init_in_cmdline(STOCK)
    assert RESIZE_INIT_ARG.encode() in out
    assert out.endswith(b"\n") and not out.endswith(b"\n\n")
    assert b"console=tty1" in out and b"rootwait" in out


def test_empty_input():
    assert ensure_resize_init_in_cmdline(b"") == (RESIZE_INIT_ARG + "\n").encode()


def test_idempotent_returns_same_object():
    pre = f"console=tty1 {RESIZE_INIT_ARG} rootwait\n".encode()
    assert ensure_resize_init_in_cmdline(pre) is pre


def test_no_trailing_newline_input_gets_one():
    out = ensure_resize_init_in_cmdline(b"console=tty1 rootwait")
    assert out.endswith(b"\n") and RESIZE_INIT_ARG.encode() in out


def test_double_application_stable():
    once = ensure_resize_init_in_cmdline(STOCK)
    assert ensure_resize_init_in_cmdline(once) == once


class _FakeBoot:
    def __init__(self, cmdline=STOCK):
        self.files = {"/cmdline.txt": cmdline}
        self.read_raises = None
        self.write_raises = None

    def read_bytes(self, path):
        if self.read_raises:
            raise self.read_raises
        return self.files[path]

    def write_bytes(self, path, data):
        if self.write_raises:
            raise self.write_raises
        self.files[path] = data


def test_inject_writes_once_then_noop():
    boot = _FakeBoot()
    assert inject_resize_arg(boot) is True
    assert RESIZE_INIT_ARG.encode() in boot.files["/cmdline.txt"]
    # second call: arg already present → no write
    assert inject_resize_arg(boot) is False


def test_inject_read_failure_raises():
    boot = _FakeBoot()
    boot.read_raises = OSError("disk error")
    with pytest.raises(CmdlineInjectionFailedError, match="Could not read"):
        inject_resize_arg(boot)


def test_inject_write_failure_raises():
    boot = _FakeBoot()
    boot.write_raises = OSError("write error")
    with pytest.raises(CmdlineInjectionFailedError, match="Could not write"):
        inject_resize_arg(boot)
