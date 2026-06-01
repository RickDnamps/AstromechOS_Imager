r"""Phase-emission contract tests for ``FlashJob.run()``.

Pins the ``phase="customizing"`` ping that the orchestrator fires when
the customize step begins. Without that ping, the global progress bar
in Step5Flash sits at 100% for 2-5 s while FAT32 writes happen, which
operators perceive as a freeze.

Symmetric to the existing ``preparing`` ping locked in by
``test_flash_view_model_phases.py``.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from astromechos_imager.core.diskwriter import DiskWriterProgress, DiskWriteResult
from astromechos_imager.core.models import DiskRef, FirstbootConfig, Role
from astromechos_imager.core.orchestrator import FlashJob


def _build_job(
    *,
    fake_platform_io,
    on_progress,
    skip_customize: bool = False,
) -> FlashJob:
    fake_platform_io.add_drive(7, size=1 << 24)  # 16 MB sparse
    target = fake_platform_io.enumerate_removable_drives()[0]
    cfg = FirstbootConfig(
        authorized_keys=["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@l"],
        imager_version="0.1.0",
        flashed_at_iso="2026-05-31T00:00:00Z",
    )
    return FlashJob(
        platform_io=fake_platform_io,
        image_path=Path("/dev/null"),
        target=target,
        role=Role.MASTER,
        firstboot_config=cfg,
        master_pair=MagicMock(),
        on_progress=on_progress,
        skip_verify=True,
        skip_customize=skip_customize,
    )


class _StubDiskWriter:
    """Drop-in for ``DiskWriter`` that does NOTHING and returns a fake result.

    Avoids exercising the real lzma/decompress path so the test pins
    only the phase-emit contract.
    """

    def __init__(self, source, raw_device, on_progress=None, cancel_event=None):
        self._on_progress = on_progress

    def run(self) -> DiskWriteResult:
        # Caller passes the read deferred-first-block bytes back into
        # ``dev.write(0, …)`` so the size must equal what we report.
        first_block = b"\x00" * 512
        return DiskWriteResult(
            bytes_written=len(first_block),
            source_sha256="0" * 64,
            first_block_data=first_block,
        )


@patch("astromechos_imager.core.orchestrator._bootpartition_open",
       lambda *a, **kw: None)
@patch("astromechos_imager.core.orchestrator.DiskWriter", _StubDiskWriter)
@patch("astromechos_imager.core.orchestrator.open_image")
def test_flash_job_emits_customizing_before_bootpartition(
    open_image_mock, fake_platform_io,
):
    """The customize block MUST emit ``phase=customizing`` before
    diving into ``update_disk_properties`` / ``_bootpartition_open``."""
    open_image_mock.return_value.__enter__.return_value = b""
    captured: list[DiskWriterProgress] = []

    job = _build_job(
        fake_platform_io=fake_platform_io,
        on_progress=captured.append,
        skip_customize=False,
    )
    result = job.run()
    assert result.ok, f"FlashJob failed: {result.error!r}"

    phases = [p.phase for p in captured]
    assert "customizing" in phases, (
        f"expected at least one 'customizing' emit; got phases={phases!r}"
    )


@patch("astromechos_imager.core.orchestrator._bootpartition_open",
       lambda *a, **kw: None)
@patch("astromechos_imager.core.orchestrator.DiskWriter", _StubDiskWriter)
@patch("astromechos_imager.core.orchestrator.open_image")
def test_flash_job_no_customizing_when_skip_customize(
    open_image_mock, fake_platform_io,
):
    """When ``skip_customize=True``, no ``customizing`` ping must fire."""
    open_image_mock.return_value.__enter__.return_value = b""
    captured: list[DiskWriterProgress] = []

    job = _build_job(
        fake_platform_io=fake_platform_io,
        on_progress=captured.append,
        skip_customize=True,
    )
    result = job.run()
    assert result.ok, f"FlashJob failed: {result.error!r}"

    phases = [p.phase for p in captured]
    assert "customizing" not in phases, (
        f"skip_customize=True must NOT emit 'customizing'; got phases={phases!r}"
    )
