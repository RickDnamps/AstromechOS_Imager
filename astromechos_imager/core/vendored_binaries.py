"""Runtime resolver for vendored binaries bundled with AstromechOS Imager.

In dev mode (not frozen), binaries are resolved from ``<project_root>/vendor/``.
In frozen mode (PyInstaller ``sys.frozen``), they are resolved from
``<sys._MEIPASS>/vendor/`` inside the extracted bundle.

Usage::

    from astromechos_imager.core.vendored_binaries import debugfs_exe, e2fsck_exe

    proc = subprocess.run([str(debugfs_exe()), ...])

See ``vendor/README.md`` for instructions on populating the ``vendor/``
directory before running in dev mode or building with PyInstaller.
"""
from __future__ import annotations

import sys
from pathlib import Path


def vendor_root() -> Path:
    """Return the directory containing the vendored binaries.

    - **Frozen** (PyInstaller): ``<sys._MEIPASS>/vendor``
    - **Dev**: ``<project_root>/vendor`` (two parents above this file)
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "vendor"  # type: ignore[attr-defined]
    # Dev mode: walk up from this file to the project root
    here = Path(__file__).resolve()
    # here: astromechos_imager/core/vendored_binaries.py
    # parents[0] = core/
    # parents[1] = astromechos_imager/
    # parents[2] = <project_root>/
    return here.parents[2] / "vendor"


def debugfs_exe() -> Path:
    """Return the path to ``debugfs.exe``.

    Raises
    ------
    RuntimeError
        When ``debugfs.exe`` is not present in the vendor directory.
        The error message explains how to fix the situation for both dev
        (populate ``vendor/``) and frozen (rebuild the PyInstaller bundle).
    """
    p = vendor_root() / "debugfs.exe"
    if not p.is_file():
        raise RuntimeError(
            f"debugfs.exe not found at {p}. "
            "Populate vendor/ per vendor/README.md (dev) or rebuild the PyInstaller bundle."
        )
    return p


def e2fsck_exe() -> Path:
    """Return the path to ``e2fsck.exe``.

    Raises
    ------
    RuntimeError
        When ``e2fsck.exe`` is not present in the vendor directory.
    """
    p = vendor_root() / "e2fsck.exe"
    if not p.is_file():
        raise RuntimeError(
            f"e2fsck.exe not found at {p}. See vendor/README.md."
        )
    return p
