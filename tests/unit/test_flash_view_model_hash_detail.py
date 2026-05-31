"""Operator-actionable SHA-256 mismatch messaging.

The legacy mismatch error ("SHA-256 mismatch on {role} image — file looks
corrupted") routinely sent operators chasing the wrong cause: customization
gets blamed even though customization writes ONLY to the SD card, never to
the source .img.gz file. The real cause is almost always a stale
``<image>.sha256`` sidecar that survived a golden-image regeneration.

These tests pin the new error contract so a regression to the legacy
single-line message fails loud.

They also pin the updated ``find_sidecar_checksum`` return shape, which
now includes the path of the sidecar file the expected digest came from
so operator-facing errors can name it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from PySide6.QtCore import QCoreApplication


@pytest.fixture(scope="module", autouse=True)
def _qcoreapp():
    """FlashViewModel is a QObject — instantiation requires a live
    QCoreApplication to back Signal emission. Module-scoped + autouse so
    every test in this file gets the same one (Qt allows only one)."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv or ["test"])
    yield app


# ── direct helper tests (no Qt event loop required) ─────────────────


def _make_vm_with_paths(master_path: str, slave_path: str = ""):
    """Construct a FlashViewModel against a minimal SimpleNamespace
    WizardState. We only need the two image path attributes for the
    detailed-error helper — no event loop, no real disk I/O.
    """
    from astromechos_imager.ui.flash_view_model import FlashViewModel

    fake_wizard = SimpleNamespace(
        masterImagePath=master_path,
        slaveImagePath=slave_path,
        currentRole="master",
    )
    return FlashViewModel(fake_wizard)


def test_hash_mismatch_error_includes_sidecar_path():
    """Operator MUST be told which file the expected digest came from —
    otherwise they cannot tell a stale sidecar from a corrupt image."""
    vm = _make_vm_with_paths(r"K:\master_golden.img.gz")
    vm._master_sidecar = (
        "sha256",
        "a" * 64,
        Path(r"K:\master_golden.img.gz.sha256"),
    )
    vm._fail_verify_with_detail(
        role="master",
        image_path=Path(r"K:\master_golden.img.gz"),
        sidecar_path=Path(r"K:\master_golden.img.gz.sha256"),
        expected_hex="a" * 64,
        computed_hex="b" * 64,
    )

    assert vm._status == "error"
    assert "master_golden.img.gz.sha256" in vm._error_message, (
        f"expected sidecar filename in error, got: {vm._error_message!r}"
    )
    assert "Sidecar:" in vm._error_message


def test_hash_mismatch_error_includes_both_hashes():
    """Both digests (truncated to first 16 chars) MUST appear so the
    operator can eyeball whether the sidecar was regenerated for a
    different build vs. the image being genuinely corrupt."""
    vm = _make_vm_with_paths(r"K:\slave_golden.img.gz", r"K:\slave_golden.img.gz")
    expected = "1234567890abcdef" + "f" * 48  # 64 hex chars total
    computed = "fedcba0987654321" + "0" * 48

    vm._fail_verify_with_detail(
        role="slave",
        image_path=Path(r"K:\slave_golden.img.gz"),
        sidecar_path=Path(r"K:\slave_golden.img.gz.sha256"),
        expected_hex=expected,
        computed_hex=computed,
    )

    assert expected[:16] in vm._error_message, (
        f"expected first 16 chars of expected hash in error, got: "
        f"{vm._error_message!r}"
    )
    assert computed[:16] in vm._error_message, (
        f"expected first 16 chars of computed hash in error, got: "
        f"{vm._error_message!r}"
    )
    assert "Expected:" in vm._error_message
    assert "Computed:" in vm._error_message


def test_hash_mismatch_error_suggests_bypass_option():
    """The remediation hint must mention BOTH options:
      1. Regenerate via ``sha256sum`` (the common case after a
         golden-image rebuild)
      2. Toggle off "VERIFY IMAGE INTEGRITY" on Step 5 (escape hatch)
    """
    vm = _make_vm_with_paths(r"K:\foo.img.gz")
    vm._fail_verify_with_detail(
        role="master",
        image_path=Path(r"K:\foo.img.gz"),
        sidecar_path=Path(r"K:\foo.img.gz.sha256"),
        expected_hex="a" * 64,
        computed_hex="b" * 64,
    )

    msg = vm._error_message
    assert "sha256sum" in msg, (
        f"expected `sha256sum` regenerate hint, got: {msg!r}"
    )
    assert "VERIFY IMAGE INTEGRITY" in msg, (
        f"expected Step 5 toggle name in error, got: {msg!r}"
    )
    # The sha256sum command should reference the actual file names so
    # the operator can copy-paste it.
    assert "foo.img.gz" in msg
    assert "foo.img.gz.sha256" in msg


def test_no_sidecar_soft_passes(tmp_path):
    """Regression guard: when ``find_sidecar_checksum`` returns None,
    the mismatch error MUST NOT be raised — the verify phase is allowed
    to fall through to the visual-confirm path."""
    from astromechos_imager.core.image_validator import find_sidecar_checksum

    img = tmp_path / "lonely.img.gz"
    img.write_bytes(b"\x1f\x8b\x08\x00" + b"x" * 100)
    # No sidecar exists alongside.
    result = find_sidecar_checksum(img)
    assert result is None, (
        f"expected None when no sidecar present, got: {result!r}"
    )


def test_find_sidecar_checksum_returns_path(tmp_path):
    """The updated 3-tuple return shape MUST include the path of the
    sidecar file the digest was read from so callers can surface it in
    operator-facing error messages."""
    from astromechos_imager.core.image_validator import find_sidecar_checksum

    img = tmp_path / "test.img.gz"
    img.write_bytes(b"\x1f\x8b\x08\x00" + b"x" * 100)
    sidecar = tmp_path / "test.img.gz.sha256"
    expected_hex = "deadbeefcafe" + "0" * 52  # 64 hex chars
    sidecar.write_text(f"{expected_hex}  test.img.gz\n", encoding="utf-8")

    result = find_sidecar_checksum(img)
    assert result is not None
    assert len(result) == 3, (
        f"find_sidecar_checksum must return a 3-tuple "
        f"(algo, hex, path), got len={len(result)}: {result!r}"
    )
    algo, hex_lower, sidecar_path = result
    assert algo == "sha256"
    assert hex_lower == expected_hex
    assert sidecar_path == sidecar, (
        f"returned sidecar path {sidecar_path!r} did not equal the "
        f"actual sidecar file {sidecar!r}"
    )


# ── full wired-through test (sidecar tuple → _on_hash_finished) ──


def test_on_hash_finished_mismatch_uses_cached_sidecar_for_detail(tmp_path):
    """End-to-end-ish: when a hash worker reports match=False, the
    detailed-error path must be invoked using the per-role sidecar
    tuple cached at spawn time. This catches a regression where the
    sidecar path is dropped on the floor and the legacy generic
    message is emitted instead."""
    img = tmp_path / "golden.img.gz"
    img.write_bytes(b"\x1f\x8b\x08\x00" + b"x" * 100)

    vm = _make_vm_with_paths(str(img), str(img))
    expected_hex = "a" * 64
    sidecar_path = tmp_path / "golden.img.gz.sha256"
    vm._master_sidecar = ("sha256", expected_hex, sidecar_path)
    # Avoid the hash-thread teardown branch (no thread running here).
    vm._hash_thread = None
    vm._hash_worker = None

    # Simulate the HashWorker reporting a mismatch.
    computed_hex = "b" * 64
    vm._on_hash_finished("master", computed_hex, False)

    assert vm._status == "error"
    assert "golden.img.gz.sha256" in vm._error_message
    assert expected_hex[:16] in vm._error_message
    assert computed_hex[:16] in vm._error_message
    assert "sha256sum" in vm._error_message
    assert "VERIFY IMAGE INTEGRITY" in vm._error_message
