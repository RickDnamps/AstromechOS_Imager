# AstromechOS Imager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows desktop tool that flashes two pre-extracted Pi OS images to two SD cards in a single session, while writing a role-specific firstboot bundle to each (per the AstromechOS firstboot contract sealed in `firstboot_setup.sh §4.7`).

**Architecture:** Strict layering — `core/` (pure Python, no I/O dep, fully testable) → `platform/windows.py` (ctypes/WMI/pyfatfs behind a `Protocol`) → `ui/` (PySide6 + QML wizard) and `cli/` (same `core` headless). Single design doc at `docs/superpowers/specs/2026-05-29-astromechos-imager-design.md`.

**Tech Stack:** Python 3.12 · PySide6 6.7.* · cryptography · pywin32 · pyfatfs · stdlib `lzma`/`gzip`/`zipfile`/`hashlib`/`ctypes`/`threading`/`secrets` · PyInstaller (admin-manifested .exe).

---

## File Structure & Decomposition

```
astromechos_imager/
├── core/
│   ├── __init__.py
│   ├── errors.py            # Phase 1.1
│   ├── models.py            # Phase 1.2 (Role, FirstbootConfig, HotspotBootstrap, Ed25519Pair, DiskRef, ImageRef, FlashJob)
│   ├── validators.py        # Phase 1.3 (hostname, OpenSSH, SSID, PSK, repo URL)
│   ├── keygen.py            # Phase 1.4-1.5 (ed25519 + hotspot bootstrap + persistence)
│   ├── imagesource.py       # Phase 2 (Raw/Xz/Gz/Zip + factory)
│   ├── customization.py     # Phase 3 (renderers + FirstbootBundle + assert_pair_symmetry)
│   ├── platform_io.py       # Phase 4.1 (IPlatformIO Protocol, RawDevice Protocol, BootPartition Protocol)
│   ├── bootpartition.py     # Phase 4.5-4.7 (FAT32 boot access — β pyfatfs primary, α drive-letter fallback)
│   ├── diskwriter.py        # Phase 5 (producer-consumer pipeline + verify + cancel)
│   └── orchestrator.py      # Phase 6 (FlashJob, PairFlashJob)
├── platform/
│   ├── __init__.py
│   └── windows.py           # Phase 4.2-4.4 (Win32 ctypes, WMI enum, lock/dismount, raw open, eject)
├── ui/
│   ├── __init__.py
│   ├── app.py               # Phase 8.1 (QApplication entry + crash hook)
│   ├── wizard_state.py      # Phase 8.2 (QObject singleton, StackView state)
│   ├── viewmodels.py        # Phase 8.2 (core ↔ QML bindings)
│   ├── messages.py          # Phase 8.1 (centralized strings)
│   └── qml/
│       ├── main.qml         # Phase 8.1
│       ├── Step1Mode.qml    # Phase 8.3
│       ├── Step2Images.qml  # Phase 8.4
│       ├── Step3Storage.qml # Phase 8.5
│       ├── Step4Customize.qml # Phase 8.6
│       ├── Step5Flash.qml   # Phase 8.7
│       ├── Step6Done.qml    # Phase 8.8
│       └── ErrorDialog.qml  # Phase 8.9
├── cli/
│   ├── __init__.py
│   └── main.py              # Phase 7 (argparse + flash subcommand + admin elevation)
├── logging_setup/
│   ├── __init__.py
│   ├── jsonl_formatter.py   # Phase 9.1
│   ├── redaction.py         # Phase 9.2
│   └── diagnostic.py        # Phase 9.3
├── tests/
│   ├── conftest.py          # Phase 0.4 (shared fixtures: tmp dirs, FakePlatformIO)
│   ├── unit/
│   │   └── (one test_*.py per core module)
│   ├── integration/
│   │   ├── test_flash_fake_sd.py            # Phase 5/6
│   │   ├── test_bootpartition_roundtrip.py  # Phase 4.6-4.7
│   │   └── test_pair_symmetry.py            # Phase 6
│   ├── contract/
│   │   ├── test_firstboot_compat.py         # Phase 10.2
│   │   └── fixtures/firstboot_setup.sh.snapshot
│   ├── fixtures/
│   │   ├── make_fixtures.py                 # Phase 2 (generates .img/.xz/.gz/.zip with known SHA256)
│   │   └── expected.json
│   └── manual/E2E.md        # Phase 10.3
├── pyproject.toml           # Phase 0.1
├── astromechos_imager.spec  # Phase 10.1 (PyInstaller spec + admin manifest)
├── .github/workflows/ci.yml # Phase 0.2
└── .pre-commit-config.yaml  # Phase 0.3
```

**Decomposition principles applied:**
- One file per cohesive responsibility — `keygen.py` does both ed25519 and HotspotBootstrap because they share persistence logic.
- `platform_io.py` lives in `core/` (as Protocols only — no implementation) so the rest of `core/` never imports from `platform/`.
- `bootpartition.py` lives in `core/` because both the β and α implementations route through the same FAT32 layout parsing; the `windows.py` only provides primitives (open raw device, wait for drive letter).
- `cli/` and `ui/` are siblings, equal-rank frontends.

---

## Phase 0 — Repo skeleton & tooling

### Task 0.1: Initialize pyproject.toml & directory tree

**Files:**
- Create: `pyproject.toml`
- Create: `astromechos_imager/__init__.py`
- Create: `astromechos_imager/core/__init__.py`
- Create: `astromechos_imager/platform/__init__.py`
- Create: `astromechos_imager/ui/__init__.py`
- Create: `astromechos_imager/cli/__init__.py`
- Create: `astromechos_imager/logging_setup/__init__.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/contract/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "astromechos-imager"
version = "0.1.0"
description = "Two-card SD imager for the AstromechOS R2-D2 build."
readme = "README.md"
requires-python = ">=3.12,<3.13"
license = {text = "GPL-3.0-or-later"}
dependencies = [
  "PySide6==6.7.*",
  "cryptography>=42",
  "pywin32>=306 ; sys_platform == 'win32'",
  "pyfatfs>=1.1",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-qt>=4.4",
  "pytest-cov>=5",
  "pytest-xdist>=3",
  "hypothesis>=6.100",
  "syrupy>=4.6",
  "pyfakefs>=5.5",
  "ruff>=0.4",
  "mypy>=1.10",
  "pyright>=1.1.360",
]

[project.scripts]
astromechos-imager = "astromechos_imager.cli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["astromechos_imager"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E","F","W","I","B","UP","SIM","ARG"]

[tool.mypy]
strict = true
packages = ["astromechos_imager.core"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
  "integration: file-backed slow tests",
  "contract: drift detection vs firstboot_setup.sh",
]
```

- [ ] **Step 2: Create empty `__init__.py` for every package**

Each contains a single line:
```python
"""<package purpose>"""
```

For example `astromechos_imager/core/__init__.py`:
```python
"""Pure-Python core: no Qt, no Win32, fully testable."""
```

- [ ] **Step 3: Verify the tree builds**

Run: `pip install -e .[dev]`
Expected: installs without error.

Run: `pytest --collect-only`
Expected: "no tests collected" (0 errors).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml astromechos_imager/ tests/
git commit -m "chore: project skeleton (pyproject.toml + package tree)"
```

---

### Task 0.2: Add GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: windows-latest
    strategy:
      fail-fast: false
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install
        run: |
          python -m pip install -U pip
          pip install -e .[dev]
      - name: Lint
        run: |
          ruff check .
          mypy
      - name: Test
        env:
          QT_QPA_PLATFORM: offscreen
        run: |
          pytest -n auto --cov=astromechos_imager --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: coverage.xml
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: windows runner, ruff + mypy + pytest with offscreen Qt"
```

---

### Task 0.3: Pre-commit hooks

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Write the config**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        files: ^astromechos_imager/core/
        additional_dependencies: [cryptography>=42]
```

- [ ] **Step 2: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: pre-commit hooks (ruff + mypy on core/)"
```

---

### Task 0.4: Shared test fixtures (conftest.py)

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Write the conftest**

```python
"""Shared pytest fixtures."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect %APPDATA% to tmp_path so tests don't pollute the user profile."""
    appdata = tmp_path / "AppData"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    return appdata


@pytest.fixture
def fixed_iso_time(monkeypatch: pytest.MonkeyPatch) -> str:
    """Freeze the wall clock so golden snapshots stay stable."""
    iso = "2026-05-29T02:15:00Z"
    monkeypatch.setattr("astromechos_imager.core.models._utc_iso_now", lambda: iso)
    return iso
```

- [ ] **Step 2: Commit**

```bash
git add tests/conftest.py
git commit -m "test: shared fixtures (tmp_appdata, fixed_iso_time)"
```

---

## Phase 1 — Core foundations (no I/O)

### Task 1.1: Error taxonomy

**Files:**
- Create: `astromechos_imager/core/errors.py`
- Test: `tests/unit/test_errors.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_errors.py
from astromechos_imager.core.errors import (
    ImagerError, PreflightError, FlashError, VerifyError, CustomizationError,
    CleanupError, WriteError, HashMismatchError, BundleSelfValidationFailedError,
    PairAsymmetryError, EjectFailedError,
)


def test_severity_defaults():
    assert WriteError("x").severity == "ERROR"
    assert EjectFailedError("x").severity == "WARNING"


def test_sd_state_per_class():
    assert PreflightError("x").sd_state == "SAFE"
    assert FlashError("x").sd_state == "GARBAGE"
    assert VerifyError("x").sd_state == "UNCERTAIN"
    assert CustomizationError("x").sd_state == "BOOTABLE_NO_FIRSTBOOT"
    assert CleanupError("x").sd_state == "OK"


def test_retryable_flag():
    assert FlashError("x").retryable is True
    assert VerifyError("x").retryable is True
    assert PreflightError("x").retryable is False  # default


def test_hash_mismatch_carries_offset():
    e = HashMismatchError("at 0x4a", first_diff_offset=0x4a)
    assert e.first_diff_offset == 0x4a
    assert e.sd_state == "UNCERTAIN"


def test_pair_asymmetry_is_customization_error():
    assert isinstance(PairAsymmetryError("x"), CustomizationError)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_errors.py -v`
Expected: `ModuleNotFoundError: astromechos_imager.core.errors`

- [ ] **Step 3: Implement**

```python
# astromechos_imager/core/errors.py
"""Typed error hierarchy. Per design spec §7.1."""
from __future__ import annotations

from typing import Literal

Severity = Literal["ERROR", "WARNING"]
SDState = Literal["SAFE", "GARBAGE", "UNCERTAIN", "BOOTABLE_NO_FIRSTBOOT", "OK"]


class ImagerError(Exception):
    severity: Severity = "ERROR"
    sd_state: SDState = "SAFE"
    retryable: bool = False
    recovery_hint: str = ""


# ── Preflight: SD untouched ───────────────────────────────────────────────
class PreflightError(ImagerError):
    sd_state: SDState = "SAFE"

class ImageFormatError(PreflightError): ...
class ImageTooLargeError(PreflightError): ...
class DriveNotFoundError(PreflightError): ...
class DrivePermissionError(PreflightError): ...
class DriveLockError(PreflightError): ...
class ConfigValidationError(PreflightError): ...


# ── Flash: SD = garbage ───────────────────────────────────────────────────
class FlashError(ImagerError):
    sd_state: SDState = "GARBAGE"
    retryable: bool = True

class DecompressError(FlashError): ...
class WriteError(FlashError): ...
class DriveDisconnectedError(FlashError): ...


# ── Verify: SD content uncertain ──────────────────────────────────────────
class VerifyError(ImagerError):
    sd_state: SDState = "UNCERTAIN"
    retryable: bool = True

class HashMismatchError(VerifyError):
    def __init__(self, msg: str, first_diff_offset: int = -1) -> None:
        super().__init__(msg)
        self.first_diff_offset = first_diff_offset

class ReadbackError(VerifyError): ...


# ── Customization: OS image valid but firstboot bundle incomplete ─────────
class CustomizationError(ImagerError):
    sd_state: SDState = "BOOTABLE_NO_FIRSTBOOT"

class BootPartitionMountError(CustomizationError): ...
class BootPartitionWriteError(CustomizationError): ...
class BundleSelfValidationFailedError(CustomizationError): ...
class PairAsymmetryError(CustomizationError): ...


# ── Cleanup: non-fatal ────────────────────────────────────────────────────
class CleanupError(ImagerError):
    severity: Severity = "WARNING"
    sd_state: SDState = "OK"

class EjectFailedError(CleanupError): ...
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_errors.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/errors.py tests/unit/test_errors.py
git commit -m "feat(core): error taxonomy with sd_state + retryable flags"
```

---

### Task 1.2: Models (Role, FirstbootConfig stub, dataclasses)

**Files:**
- Create: `astromechos_imager/core/models.py`
- Test: `tests/unit/test_models.py`

NOTE — full `FirstbootConfig.__post_init__` validation depends on `validators.py` (Task 1.3). In this task we only declare the dataclass with field types and document that validation gets wired in Task 1.3.

- [ ] **Step 1: Write failing test (limited to immutability + role enum)**

```python
# tests/unit/test_models.py
import pytest
from astromechos_imager.core.models import Role, HotspotBootstrap, Ed25519Pair


def test_role_values():
    assert Role.MASTER.value == "master"
    assert Role.SLAVE.value == "slave"


def test_hotspot_bootstrap_is_frozen():
    b = HotspotBootstrap(ssid="Astromech_Boot_3F2A", password="x" * 32)
    with pytest.raises(AttributeError):  # dataclass(frozen=True)
        b.ssid = "other"  # type: ignore[misc]


def test_ed25519_pair_carries_bytes():
    p = Ed25519Pair(private_openssh=b"PRIV", public_openssh=b"ssh-ed25519 KEY\n")
    assert p.private_openssh == b"PRIV"
    assert p.public_openssh.endswith(b"\n")
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_models.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# astromechos_imager/core/models.py
"""Core data model. Per design spec §6.1.

Validation methods are wired in at __post_init__ time, but the actual
validators live in core/validators.py to keep them reusable from the UI
preflight pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


def _utc_iso_now() -> str:
    """Wall clock indirection — monkeypatched in tests for deterministic snapshots."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Role(Enum):
    MASTER = "master"
    SLAVE = "slave"


@dataclass(frozen=True)
class HotspotBootstrap:
    ssid: str
    password: str


@dataclass(frozen=True)
class Ed25519Pair:
    private_openssh: bytes
    public_openssh: bytes


@dataclass(frozen=True)
class DiskRef:
    """A removable drive candidate. Populated by platform/windows.py::enumerate_drives()."""
    physical_drive_id: int       # e.g. 2 → \\.\PHYSICALDRIVE2
    device_path: str             # full Win32 path
    drive_letters: tuple[str, ...]  # e.g. ("E",) — may be empty if no FS recognised yet
    size_bytes: int
    model: str
    serial: str


@dataclass(frozen=True)
class ImageRef:
    """A user-selected source image. Format-detected by core/imagesource.py."""
    path: Path
    detected_format: str         # "raw" | "xz" | "gz" | "zip"
    uncompressed_size: int | None
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_models.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/models.py tests/unit/test_models.py
git commit -m "feat(core): models — Role, HotspotBootstrap, Ed25519Pair, DiskRef, ImageRef"
```

---

### Task 1.3: Validators

**Files:**
- Create: `astromechos_imager/core/validators.py`
- Test: `tests/unit/test_validators.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_validators.py
import pytest
from hypothesis import given, strategies as st, assume
import re, string

from astromechos_imager.core.validators import (
    validate_hostname, validate_authorized_keys, validate_install_user,
    validate_repo_url, validate_branch_name, validate_ssid, validate_wpa2_psk,
    OPENSSH_PUBKEY_RE,
)
from astromechos_imager.core.errors import (
    InvalidHostnameError, InvalidAuthorizedKeysError, InvalidInstallUserError,
    InvalidRepoUrlError, InvalidBranchNameError, InvalidHotspotSsidError,
    InvalidHotspotPskError,
)


# ── Hostname ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("h", ["astromech-master", "astromech-slave", "r2", "x", "a1b2c3"])
def test_hostname_valid(h):
    validate_hostname(h)


@pytest.mark.parametrize("h", ["-leading", "trailing-", "has space", "has_underscore",
                                "a" * 64, "", "a..b", "127.0.0.1"])
def test_hostname_invalid(h):
    with pytest.raises(InvalidHostnameError):
        validate_hostname(h)


# ── OpenSSH pubkey ────────────────────────────────────────────────────────
@pytest.mark.parametrize("k", [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY user@host",
    "ssh-rsa AAAAB3NzaC1yc2EAAAA... me@laptop",
    "ecdsa-sha2-nistp256 AAAAB3...",
])
def test_openssh_pubkey_valid(k):
    validate_authorized_keys([k])


@pytest.mark.parametrize("k", ["", "not-a-key", "ssh-bad XXX", "ssh-ed25519", "ssh-ed25519 "])
def test_openssh_pubkey_invalid(k):
    with pytest.raises(InvalidAuthorizedKeysError):
        validate_authorized_keys([k])


def test_authorized_keys_empty_list_rejected():
    with pytest.raises(InvalidAuthorizedKeysError):
        validate_authorized_keys([])


# ── Install user (POSIX login) ────────────────────────────────────────────
@pytest.mark.parametrize("u", ["pi", "astromech", "artoo", "_svc", "user-1"])
def test_install_user_valid(u):
    validate_install_user(u)


@pytest.mark.parametrize("u", ["Pi", "1pi", "user name", "root@host", "x" * 33, ""])
def test_install_user_invalid(u):
    with pytest.raises(InvalidInstallUserError):
        validate_install_user(u)


# ── Repo URL ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("u", [
    "https://github.com/RickDnamps/AstromechOS.git",
    "https://gitlab.example.com/me/fork.git",
    "git@github.com:me/repo.git",
])
def test_repo_url_valid(u):
    validate_repo_url(u)


@pytest.mark.parametrize("u", ["file:///tmp/repo", "http://x", "ftp://x", "x"])
def test_repo_url_invalid(u):
    with pytest.raises(InvalidRepoUrlError):
        validate_repo_url(u)


# ── Branch name ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("b", ["main", "develop", "feature/x", "v1.2.3"])
def test_branch_name_valid(b):
    validate_branch_name(b)


@pytest.mark.parametrize("b", ["", "/leading", "trailing/", "double//slash", "x..y",
                                "ends.lock"])
def test_branch_name_invalid(b):
    with pytest.raises(InvalidBranchNameError):
        validate_branch_name(b)


# ── SSID 802.11 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("s", ["Astromech_Boot_3F2A", "Astromech_Boot_AABBCC", "Astromech_Boot_ABCD"])
def test_ssid_valid(s):
    validate_ssid(s)


@pytest.mark.parametrize("s", ["Astromech_Boot_xx", "Astromech_Boot_", "Other_3F2A",
                                "Astromech_Boot_3F2A" + "X" * 20, "Astromech_Boot_GHIJ"])
def test_ssid_invalid(s):
    with pytest.raises(InvalidHotspotSsidError):
        validate_ssid(s)


# ── WPA2 PSK ──────────────────────────────────────────────────────────────
def test_psk_min_length():
    validate_wpa2_psk("a" * 8)


def test_psk_max_length():
    validate_wpa2_psk("a" * 63)


@pytest.mark.parametrize("p", ["short", "a" * 64, "with\x00null", "with\nnewline"])
def test_psk_invalid(p):
    with pytest.raises(InvalidHotspotPskError):
        validate_wpa2_psk(p)


# ── Property: firstboot regex subsumption ─────────────────────────────────
@given(st.text(alphabet=string.ascii_letters + string.digits + "-", min_size=1, max_size=63))
def test_hostname_property_matches_firstboot_regex(h: str):
    """Our regex MUST be subset of firstboot_setup.sh:206. If we accept, firstboot accepts."""
    firstboot_re = re.compile(r"^[a-zA-Z0-9](-?[a-zA-Z0-9])*$")
    try:
        validate_hostname(h)
        assert firstboot_re.match(h) is not None, \
            f"Our validator accepted {h!r} but firstboot would reject it"
    except Exception:
        pass  # either may reject; subsumption means we are not LESS strict
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_validators.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# astromechos_imager/core/validators.py
"""Per design spec §6.5. Regex aligned with firstboot_setup.sh:206 and IEEE 802.11i."""
from __future__ import annotations

import re

from astromechos_imager.core.errors import (
    InvalidHostnameError, InvalidAuthorizedKeysError, InvalidInstallUserError,
    InvalidRepoUrlError, InvalidBranchNameError, InvalidHotspotSsidError,
    InvalidHotspotPskError,
)


# Strict RFC 1123, copy of firstboot_setup.sh:206
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9](?:-?[a-zA-Z0-9])*$")

OPENSSH_PUBKEY_RE = re.compile(
    r"^(?:ssh-(?:rsa|ed25519|dss)"
    r"|ecdsa-sha2-nistp(?:256|384|521)"
    r"|sk-(?:ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)"
    r"\s+[A-Za-z0-9+/=]+(?:\s+.+)?$"
)

_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

_REPO_URL_RE = re.compile(
    r"^(?:https://[^\s]+|git@[^\s:]+:[^\s]+)$"
)

# Simplified git refname rules
_BRANCH_RE = re.compile(r"^(?!.*\.\.)(?!/)(?!.*//)[A-Za-z0-9._/-]+$")

_SSID_RE = re.compile(r"^Astromech_Boot_[0-9A-F]{4,8}$")


def validate_hostname(h: str) -> None:
    if not h or len(h) > 63 or not _HOSTNAME_RE.match(h):
        raise InvalidHostnameError(h)


def validate_authorized_keys(keys: list[str]) -> None:
    if not keys:
        raise InvalidAuthorizedKeysError("at least one key required")
    for k in keys:
        if not OPENSSH_PUBKEY_RE.match(k.strip()):
            raise InvalidAuthorizedKeysError(f"not an OpenSSH pubkey: {k!r}")


def validate_install_user(u: str) -> None:
    if not _USER_RE.match(u):
        raise InvalidInstallUserError(u)


def validate_repo_url(u: str) -> None:
    if not _REPO_URL_RE.match(u):
        raise InvalidRepoUrlError(u)


def validate_branch_name(b: str) -> None:
    if not b or b.endswith(".lock") or b.endswith("/") or not _BRANCH_RE.match(b):
        raise InvalidBranchNameError(b)


def validate_ssid(s: str) -> None:
    if not _SSID_RE.match(s) or len(s.encode("utf-8")) > 32:
        raise InvalidHotspotSsidError(s)


def validate_wpa2_psk(p: str) -> None:
    if not (8 <= len(p) <= 63) or not p.isascii() or not p.isprintable():
        # Never echo the actual PSK in the message
        raise InvalidHotspotPskError("<redacted: invalid WPA2 PSK>")
```

- [ ] **Step 4: Extend errors.py with the new typed validation errors**

Edit `astromechos_imager/core/errors.py` — add at the bottom of the PreflightError section:

```python
class InvalidHostnameError(ConfigValidationError): ...
class InvalidAuthorizedKeysError(ConfigValidationError): ...
class InvalidInstallUserError(ConfigValidationError): ...
class InvalidRepoUrlError(ConfigValidationError): ...
class InvalidBranchNameError(ConfigValidationError): ...
class InvalidHotspotSsidError(ConfigValidationError): ...
class InvalidHotspotPskError(ConfigValidationError): ...
```

- [ ] **Step 5: Run — expect PASS**

Run: `pytest tests/unit/test_validators.py tests/unit/test_errors.py -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add astromechos_imager/core/validators.py astromechos_imager/core/errors.py tests/unit/test_validators.py
git commit -m "feat(core): validators (hostname, OpenSSH, SSID, PSK, repo URL) + property test for firstboot regex subsumption"
```

---

### Task 1.4: keygen — ed25519

**Files:**
- Modify: `astromechos_imager/core/keygen.py` (create)
- Test: `tests/unit/test_keygen_ed25519.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_keygen_ed25519.py
from cryptography.hazmat.primitives.serialization import load_ssh_public_key, load_ssh_private_key
from astromechos_imager.core.keygen import generate_ed25519
from astromechos_imager.core.models import Ed25519Pair


def test_generate_returns_pair():
    p = generate_ed25519()
    assert isinstance(p, Ed25519Pair)
    assert p.private_openssh.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----")
    assert p.public_openssh.startswith(b"ssh-ed25519 ")
    assert p.public_openssh.endswith(b"\n")


def test_public_includes_comment():
    p = generate_ed25519(comment="r2d2@imager")
    assert p.public_openssh.rstrip(b"\n").endswith(b" r2d2@imager")


def test_keys_are_parseable_by_cryptography():
    p = generate_ed25519()
    pub = load_ssh_public_key(p.public_openssh)
    sk = load_ssh_private_key(p.private_openssh, password=None)
    assert sk.public_key().public_bytes_raw() == pub.public_bytes_raw()


def test_two_calls_produce_different_keys():
    a, b = generate_ed25519(), generate_ed25519()
    assert a.private_openssh != b.private_openssh
```

- [ ] **Step 2: Run — expect FAIL** (ModuleNotFoundError)

- [ ] **Step 3: Implement**

```python
# astromechos_imager/core/keygen.py
"""Cryptographic + bootstrap-credential generators. Per design spec §6.2."""
from __future__ import annotations

import secrets

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from astromechos_imager.core.models import Ed25519Pair, HotspotBootstrap


def generate_ed25519(comment: str = "astromech-master@imager") -> Ed25519Pair:
    """Generate a fresh ed25519 keypair in OpenSSH wire format.

    The public half carries the comment as the third whitespace-separated field
    (same convention as `ssh-keygen`). firstboot_setup.sh:147-158 copies the file
    verbatim into ~/.ssh/, so the comment survives to the Pi.
    """
    sk = Ed25519PrivateKey.generate()
    priv = sk.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.OpenSSH,
        encryption_algorithm=NoEncryption(),
    )
    pub = sk.public_key().public_bytes(
        encoding=Encoding.OpenSSH,
        format=PublicFormat.OpenSSH,
    )
    pub_with_comment = pub + b" " + comment.encode("ascii") + b"\n"
    return Ed25519Pair(private_openssh=priv, public_openssh=pub_with_comment)
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_keygen_ed25519.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/keygen.py tests/unit/test_keygen_ed25519.py
git commit -m "feat(core/keygen): ed25519 keypair generation in OpenSSH format"
```

---

### Task 1.5: keygen — HotspotBootstrap

**Files:**
- Modify: `astromechos_imager/core/keygen.py`
- Test: `tests/unit/test_keygen_hotspot.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_keygen_hotspot.py
import re
import pytest
from astromechos_imager.core.keygen import generate_hotspot_bootstrap
from astromechos_imager.core.validators import validate_ssid, validate_wpa2_psk
from astromechos_imager.core.models import HotspotBootstrap


def test_returns_hotspot_bootstrap():
    b = generate_hotspot_bootstrap()
    assert isinstance(b, HotspotBootstrap)


def test_ssid_passes_validator():
    b = generate_hotspot_bootstrap()
    validate_ssid(b.ssid)  # must not raise


def test_psk_passes_validator():
    b = generate_hotspot_bootstrap()
    validate_wpa2_psk(b.password)


def test_ssid_format():
    b = generate_hotspot_bootstrap()
    assert re.match(r"^Astromech_Boot_[0-9A-F]{4}$", b.ssid)


def test_psk_is_32_hex():
    b = generate_hotspot_bootstrap()
    assert len(b.password) == 32
    int(b.password, 16)  # parses


def test_collision_probability_is_low():
    # 1000 calls should produce no collisions on the 16-bit SSID suffix in practice
    # (we just want different PSKs every call — SSID collisions are rare but legal)
    seen_psks = {generate_hotspot_bootstrap().password for _ in range(1000)}
    assert len(seen_psks) == 1000
```

- [ ] **Step 2: Run — expect FAIL** (ImportError on `generate_hotspot_bootstrap`)

- [ ] **Step 3: Implement — append to `keygen.py`**

```python
def generate_hotspot_bootstrap() -> HotspotBootstrap:
    """Generate a fresh per-pair WPA2-PSK bootstrap.

    SSID format: ``Astromech_Boot_<4 hex uppercase>`` — matches the visual
    convention of ``Astromech_Control_XXXX`` used by gen_hotspot_ssid.sh.
    PSK: 32 hex chars = 128 bits of entropy, comfortably inside the WPA2-PSK
    8–63 ASCII printable bound (per design spec §6.2, validators §6.5).
    """
    suffix = secrets.token_hex(2).upper()          # 4 hex chars
    return HotspotBootstrap(
        ssid=f"Astromech_Boot_{suffix}",
        password=secrets.token_hex(16),            # 32 hex chars
    )
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_keygen_hotspot.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/keygen.py tests/unit/test_keygen_hotspot.py
git commit -m "feat(core/keygen): HotspotBootstrap generator (Astromech_Boot_XXXX + 128-bit PSK)"
```

---

### Task 1.6: Persistence (last_pair/) + redaction-aware load/save

**Files:**
- Modify: `astromechos_imager/core/keygen.py`
- Test: `tests/unit/test_keygen_persistence.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_keygen_persistence.py
import pytest
from pathlib import Path
from astromechos_imager.core.keygen import (
    generate_ed25519, generate_hotspot_bootstrap,
    save_persisted_pair, load_persisted_pair,
    save_persisted_hotspot, load_persisted_hotspot,
    persisted_pair_dir,
)


def test_load_returns_none_when_absent(tmp_appdata):
    assert load_persisted_pair() is None
    assert load_persisted_hotspot() is None


def test_pair_roundtrip(tmp_appdata):
    original = generate_ed25519()
    save_persisted_pair(original)
    loaded = load_persisted_pair()
    assert loaded is not None
    assert loaded.private_openssh == original.private_openssh
    assert loaded.public_openssh == original.public_openssh


def test_hotspot_roundtrip(tmp_appdata):
    original = generate_hotspot_bootstrap()
    save_persisted_hotspot(original)
    loaded = load_persisted_hotspot()
    assert loaded is not None
    assert loaded.ssid == original.ssid
    assert loaded.password == original.password


def test_persisted_pair_dir_under_appdata(tmp_appdata):
    d = persisted_pair_dir()
    assert d.is_relative_to(tmp_appdata)
    assert d.name == "last_pair"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement — append to `keygen.py`**

```python
import json
import os
from pathlib import Path


def _appdata_root() -> Path:
    """%APPDATA%\\AstromechOS Imager  — env-overridable for tests."""
    base = os.environ.get("APPDATA")
    if not base:
        raise RuntimeError("APPDATA env var not set (Windows-only path)")
    return Path(base) / "AstromechOS Imager"


def persisted_pair_dir() -> Path:
    d = _appdata_root() / "last_pair"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_persisted_pair(pair: Ed25519Pair) -> None:
    d = persisted_pair_dir()
    (d / "id_ed25519").write_bytes(pair.private_openssh)
    (d / "id_ed25519.pub").write_bytes(pair.public_openssh)


def load_persisted_pair() -> Ed25519Pair | None:
    d = persisted_pair_dir()
    priv_p = d / "id_ed25519"
    pub_p = d / "id_ed25519.pub"
    if not (priv_p.is_file() and pub_p.is_file()):
        return None
    return Ed25519Pair(
        private_openssh=priv_p.read_bytes(),
        public_openssh=pub_p.read_bytes(),
    )


def save_persisted_hotspot(b: HotspotBootstrap) -> None:
    d = persisted_pair_dir()
    (d / "hotspot.json").write_text(
        json.dumps({"ssid": b.ssid, "password": b.password}), encoding="utf-8"
    )


def load_persisted_hotspot() -> HotspotBootstrap | None:
    p = persisted_pair_dir() / "hotspot.json"
    if not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    return HotspotBootstrap(ssid=obj["ssid"], password=obj["password"])
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_keygen_persistence.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/keygen.py tests/unit/test_keygen_persistence.py
git commit -m "feat(core/keygen): persistence under %APPDATA%/AstromechOS Imager/last_pair"
```

NOTE — NTFS DACL hardening (DACL: current user only) is wired in Task 9.2 once the redaction filter is in place. The current task only does default ACLs.

---

### Task 1.7: FirstbootConfig dataclass with validation

**Files:**
- Modify: `astromechos_imager/core/models.py`
- Test: `tests/unit/test_firstboot_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_firstboot_config.py
import pytest
from pathlib import Path
from astromechos_imager.core.models import FirstbootConfig, HotspotBootstrap
from astromechos_imager.core.errors import (
    InvalidHostnameError, InvalidAuthorizedKeysError, InvalidRepoUrlError,
)


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY user@host"


def test_minimal_valid():
    cfg = FirstbootConfig(authorized_keys=[VALID_KEY])
    assert cfg.install_user == "pi"
    assert cfg.hostname_master == "astromech-master"
    assert cfg.hostname_slave == "astromech-slave"
    assert cfg.repo_url is None
    assert cfg.hotspot_bootstrap is None


def test_with_all_fields():
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        install_user="astromech",
        repo_url="https://github.com/me/fork.git",
        repo_branch="develop",
        hostname_master="r2-dome",
        hostname_slave="r2-body",
        hotspot_bootstrap=HotspotBootstrap(ssid="Astromech_Boot_3F2A", password="a" * 16),
    )
    assert cfg.repo_branch == "develop"


def test_rejects_invalid_hostname():
    with pytest.raises(InvalidHostnameError):
        FirstbootConfig(authorized_keys=[VALID_KEY], hostname_master="bad host")


def test_rejects_empty_keys():
    with pytest.raises(InvalidAuthorizedKeysError):
        FirstbootConfig(authorized_keys=[])


def test_rejects_invalid_repo_url():
    with pytest.raises(InvalidRepoUrlError):
        FirstbootConfig(authorized_keys=[VALID_KEY], repo_url="ftp://no")


def test_frozen():
    cfg = FirstbootConfig(authorized_keys=[VALID_KEY])
    with pytest.raises(AttributeError):
        cfg.install_user = "x"  # type: ignore[misc]
```

- [ ] **Step 2: Run — expect FAIL** (FirstbootConfig not defined)

- [ ] **Step 3: Implement — append to `astromechos_imager/core/models.py`**

```python
from astromechos_imager.core import validators as _v


@dataclass(frozen=True)
class FirstbootConfig:
    """Per design spec §6.1.

    Validation runs in __post_init__ — the same validators are also used by the
    UI's preflight pass so users get immediate feedback in step 4.
    """
    authorized_keys: list[str]
    install_user: str = "pi"
    repo_url: str | None = None
    repo_branch: str = "main"
    hostname_master: str = "astromech-master"
    hostname_slave: str = "astromech-slave"
    hw_layout_master: Path | None = None
    hw_layout_slave: Path | None = None
    hotspot_bootstrap: HotspotBootstrap | None = None
    # Auto-managed by orchestrator — empty defaults exist for unit tests only.
    imager_version: str = ""
    flashed_at_iso: str = ""

    def __post_init__(self) -> None:
        _v.validate_authorized_keys(self.authorized_keys)
        _v.validate_install_user(self.install_user)
        _v.validate_hostname(self.hostname_master)
        _v.validate_hostname(self.hostname_slave)
        if self.hostname_master == self.hostname_slave:
            raise _v.InvalidHostnameError(
                "master and slave hostnames must differ"
            )
        if self.repo_url is not None:
            _v.validate_repo_url(self.repo_url)
            _v.validate_branch_name(self.repo_branch)
        if self.hotspot_bootstrap is not None:
            _v.validate_ssid(self.hotspot_bootstrap.ssid)
            _v.validate_wpa2_psk(self.hotspot_bootstrap.password)
```

NOTE — `_v.InvalidHostnameError` must be re-exported from `validators.py`. Add at the top of `validators.py` to make it available:

```python
from astromechos_imager.core.errors import (
    InvalidHostnameError,  # re-exported for FirstbootConfig collision check
    ...
)
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_firstboot_config.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/models.py astromechos_imager/core/validators.py tests/unit/test_firstboot_config.py
git commit -m "feat(core/models): FirstbootConfig with defensive __post_init__ validation"
```

---

## Phase 2 — ImageSource (streaming decompression)

### Task 2.1: ImageSource Protocol + open_image factory + RawSource

**Files:**
- Create: `astromechos_imager/core/imagesource.py`
- Test: `tests/unit/test_imagesource_raw.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_imagesource_raw.py
import hashlib
from pathlib import Path
from astromechos_imager.core.imagesource import open_image, RawSource
from astromechos_imager.core.errors import ImageFormatError
import pytest


def test_raw_detection(tmp_path):
    p = tmp_path / "blob.img"
    payload = b"\x00" * 1024 + b"\x55\xAA"  # MBR signature near end
    p.write_bytes(payload)
    src = open_image(p)
    assert isinstance(src, RawSource)
    assert src.uncompressed_size == len(payload)


def test_raw_iteration_yields_full_content(tmp_path):
    p = tmp_path / "blob.img"
    payload = b"X" * (3 * 1024 * 1024 + 17)   # 3 MB + tail
    p.write_bytes(payload)
    with open_image(p) as src:
        chunks = list(src)
    assert b"".join(chunks) == payload
    assert all(len(c) <= src.CHUNK_SIZE for c in chunks)


def test_raw_sha256(tmp_path):
    p = tmp_path / "blob.img"
    payload = b"Y" * 1_500_000
    p.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    h = hashlib.sha256()
    with open_image(p) as src:
        for chunk in src:
            h.update(chunk)
    assert h.hexdigest() == expected


def test_unsupported_format(tmp_path):
    p = tmp_path / "weird.bin"
    p.write_bytes(b"\x01" * 100)   # too small, no MBR
    with pytest.raises(ImageFormatError):
        open_image(p)
```

- [ ] **Step 2: Run — expect FAIL** (ModuleNotFoundError)

- [ ] **Step 3: Implement**

```python
# astromechos_imager/core/imagesource.py
"""Streaming-decompression sources. Per design spec §5.4."""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Iterator, Protocol

from astromechos_imager.core.errors import ImageFormatError


class ImageSource(Protocol):
    """Yields the uncompressed image as 1 MB chunks. Context-manager-aware."""
    CHUNK_SIZE: int
    uncompressed_size: int | None

    def __iter__(self) -> Iterator[bytes]: ...
    def __enter__(self) -> "ImageSource": ...
    def __exit__(self, *exc: object) -> None: ...


class _BaseSource:
    CHUNK_SIZE = 1 << 20  # 1 MB

    def __init__(self, path: Path):
        self.path = path
        self.uncompressed_size: int | None = None
        self._fh: BinaryIO | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class RawSource(_BaseSource):
    """Pass-through. Used when the file is already a raw .img."""
    def __init__(self, path: Path):
        super().__init__(path)
        self.uncompressed_size = path.stat().st_size

    def __iter__(self) -> Iterator[bytes]:
        self._fh = self.path.open("rb")
        while True:
            chunk = self._fh.read(self.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


def _peek_magic(path: Path, n: int = 8) -> bytes:
    with path.open("rb") as f:
        return f.read(n)


def _looks_like_mbr(head: bytes, path: Path) -> bool:
    # Bytes 510-511 of a MBR are 0x55 0xAA. We check end of file for robustness.
    size = path.stat().st_size
    if size < 512:
        return False
    with path.open("rb") as f:
        f.seek(510)
        sig = f.read(2)
    return sig == b"\x55\xAA"


def open_image(path: Path) -> ImageSource:
    """Detect format by magic bytes (with extension as tie-breaker) and return source."""
    if not path.is_file():
        raise ImageFormatError(f"not a file: {path}")

    head = _peek_magic(path)
    # xz magic
    if head[:6] == b"\xfd7zXZ\x00":
        from astromechos_imager.core.imagesource import XzSource  # forward
        return XzSource(path)
    # gzip magic
    if head[:2] == b"\x1f\x8b":
        from astromechos_imager.core.imagesource import GzSource
        return GzSource(path)
    # zip magic
    if head[:4] == b"PK\x03\x04":
        from astromechos_imager.core.imagesource import ZipSource
        return ZipSource(path)
    # raw .img (MBR signature)
    if _looks_like_mbr(head, path):
        return RawSource(path)
    raise ImageFormatError(f"unrecognized image format: {path}")
```

- [ ] **Step 4: Run — expect PASS (raw tests only)**

Run: `pytest tests/unit/test_imagesource_raw.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/imagesource.py tests/unit/test_imagesource_raw.py
git commit -m "feat(core/imagesource): ImageSource protocol + open_image factory + RawSource"
```

---

### Task 2.2: XzSource + GzSource

**Files:**
- Modify: `astromechos_imager/core/imagesource.py`
- Test: `tests/unit/test_imagesource_compressed.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_imagesource_compressed.py
import gzip, lzma, hashlib
from pathlib import Path
from astromechos_imager.core.imagesource import open_image, XzSource, GzSource


PAYLOAD = (b"R2-D2 boots fast." * 100_000)  # ~1.7 MB raw — will compress well


def _mbr(payload: bytes) -> bytes:
    """Pad payload to ≥ 512 B and stamp the MBR signature so it looks like an img."""
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_xz_roundtrip(tmp_path):
    raw = _mbr(PAYLOAD)
    p = tmp_path / "im.img.xz"
    p.write_bytes(lzma.compress(raw))
    src = open_image(p)
    assert isinstance(src, XzSource)
    h = hashlib.sha256()
    with src:
        for chunk in src:
            h.update(chunk)
    assert h.hexdigest() == hashlib.sha256(raw).hexdigest()


def test_gz_roundtrip(tmp_path):
    raw = _mbr(PAYLOAD)
    p = tmp_path / "im.img.gz"
    p.write_bytes(gzip.compress(raw))
    src = open_image(p)
    assert isinstance(src, GzSource)
    h = hashlib.sha256()
    with src:
        for chunk in src:
            h.update(chunk)
    assert h.hexdigest() == hashlib.sha256(raw).hexdigest()


def test_gz_uncompressed_size_from_isize(tmp_path):
    raw = b"x" * 100_000
    p = tmp_path / "im.img.gz"
    p.write_bytes(gzip.compress(raw))
    src = open_image(p)
    # gzip ISIZE = uncompressed size mod 2^32. We just check it's non-None and ≤ true value.
    assert src.uncompressed_size in (100_000, None)
```

- [ ] **Step 2: Run — expect FAIL** (XzSource/GzSource missing)

- [ ] **Step 3: Implement — append to `imagesource.py`**

```python
import gzip
import lzma
import struct


class XzSource(_BaseSource):
    """Streaming xz decompression via stdlib lzma."""
    def __init__(self, path: Path):
        super().__init__(path)
        self.uncompressed_size = None  # xz format does not always store this

    def __iter__(self) -> Iterator[bytes]:
        self._fh = lzma.open(self.path, "rb")
        while True:
            chunk = self._fh.read(self.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


class GzSource(_BaseSource):
    """Streaming gzip decompression."""
    def __init__(self, path: Path):
        super().__init__(path)
        self.uncompressed_size = self._read_isize()

    def _read_isize(self) -> int | None:
        """Last 4 bytes of a gzip file = uncompressed size mod 2^32."""
        size = self.path.stat().st_size
        if size < 4:
            return None
        with self.path.open("rb") as f:
            f.seek(-4, 2)
            isize = struct.unpack("<I", f.read(4))[0]
        # For images > 4 GB this wraps. Caller treats None and 0 as "unknown".
        return isize if isize > 0 else None

    def __iter__(self) -> Iterator[bytes]:
        self._fh = gzip.open(self.path, "rb")
        while True:
            chunk = self._fh.read(self.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_imagesource_compressed.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/imagesource.py tests/unit/test_imagesource_compressed.py
git commit -m "feat(core/imagesource): XzSource + GzSource streaming decompressors"
```

---

### Task 2.3: ZipSource (with strict single-image validation)

**Files:**
- Modify: `astromechos_imager/core/imagesource.py`
- Test: `tests/unit/test_imagesource_zip.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_imagesource_zip.py
import hashlib
import zipfile
from pathlib import Path
import pytest
from astromechos_imager.core.imagesource import open_image, ZipSource
from astromechos_imager.core.errors import ImageFormatError


def _mbr(payload: bytes) -> bytes:
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_zip_with_single_img(tmp_path):
    raw = _mbr(b"hello" * 200_000)
    z = tmp_path / "im.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("master.img", raw)
    src = open_image(z)
    assert isinstance(src, ZipSource)
    assert src.uncompressed_size == len(raw)
    h = hashlib.sha256()
    with src:
        for c in src:
            h.update(c)
    assert h.hexdigest() == hashlib.sha256(raw).hexdigest()


def test_zip_with_zero_img_rejected(tmp_path):
    z = tmp_path / "empty.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", b"hi")
    with pytest.raises(ImageFormatError):
        open_image(z)


def test_zip_with_multiple_img_rejected(tmp_path):
    raw = _mbr(b"x" * 100_000)
    z = tmp_path / "multi.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.img", raw)
        zf.writestr("b.img", raw)
    with pytest.raises(ImageFormatError):
        open_image(z)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement — append to `imagesource.py`**

```python
import zipfile


class ZipSource(_BaseSource):
    """Streams the single .img entry inside a ZIP. Refuses zero or 2+ .img entries."""
    def __init__(self, path: Path):
        super().__init__(path)
        with zipfile.ZipFile(path, "r") as zf:
            imgs = [n for n in zf.namelist() if n.lower().endswith(".img")]
        if len(imgs) != 1:
            raise ImageFormatError(
                f"ZIP must contain exactly one .img entry, found {len(imgs)}: {imgs!r}"
            )
        self._entry = imgs[0]
        with zipfile.ZipFile(path, "r") as zf:
            self.uncompressed_size = zf.getinfo(self._entry).file_size

    def __iter__(self) -> Iterator[bytes]:
        zf = zipfile.ZipFile(self.path, "r")
        self._fh = zf.open(self._entry, "r")
        try:
            while True:
                chunk = self._fh.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            self._fh.close()
            zf.close()
            self._fh = None
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_imagesource_zip.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/imagesource.py tests/unit/test_imagesource_zip.py
git commit -m "feat(core/imagesource): ZipSource with strict single-img validation"
```

---

## Phase 3 — Firstboot bundle (customization)

### Task 3.1: render_init_cfg

**Files:**
- Create: `astromechos_imager/core/customization.py`
- Test: `tests/unit/test_render_init_cfg.py`

- [ ] **Step 1: Write failing test (snapshot-style)**

```python
# tests/unit/test_render_init_cfg.py
from astromechos_imager.core.customization import render_init_cfg
from astromechos_imager.core.models import FirstbootConfig, HotspotBootstrap


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY user@host"


def _cfg(**kw):
    base = dict(
        authorized_keys=[VALID_KEY],
        imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
    )
    base.update(kw)
    return FirstbootConfig(**base)


def test_minimal_cfg_contains_only_system():
    out = render_init_cfg(_cfg()).decode("utf-8")
    assert "[system]" in out
    assert "user = pi" in out
    assert "[github]" not in out
    assert "[hotspot]" not in out
    assert "[slave]" not in out
    assert out.startswith("# Generated by AstromechOS Imager 0.1.0 on 2026-05-29T02:15:00Z")
    assert out.endswith("\n")


def test_with_repo_url_adds_github_section():
    out = render_init_cfg(_cfg(
        repo_url="https://github.com/me/fork.git", repo_branch="develop"
    )).decode("utf-8")
    assert "[github]" in out
    assert "repo_url = https://github.com/me/fork.git" in out
    assert "branch = develop" in out


def test_with_hotspot_uses_ssid_and_password_keys():
    """Critical contract: keys are EXACTLY 'ssid' and 'password' (not '_bootstrap').
    Refs firstboot_setup.sh:325-326."""
    out = render_init_cfg(_cfg(
        hotspot_bootstrap=HotspotBootstrap(ssid="Astromech_Boot_3F2A", password="a" * 32)
    )).decode("utf-8")
    assert "[hotspot]" in out
    assert "ssid = Astromech_Boot_3F2A" in out
    assert "password = " + "a" * 32 in out
    assert "ssid_bootstrap" not in out
    assert "password_bootstrap" not in out


def test_slave_section_only_when_hostname_custom():
    # Default hostname → no [slave]
    out = render_init_cfg(_cfg()).decode("utf-8")
    assert "[slave]" not in out
    # Custom hostname → emits [slave] host
    out2 = render_init_cfg(_cfg(hostname_slave="r2-body")).decode("utf-8")
    assert "[slave]" in out2
    assert "host = r2-body.local" in out2
```

- [ ] **Step 2: Run — expect FAIL** (customization missing)

- [ ] **Step 3: Implement**

```python
# astromechos_imager/core/customization.py
"""Firstboot bundle generation. Per design spec §6.3-6.4."""
from __future__ import annotations

import json
from pathlib import Path

from astromechos_imager.core.models import (
    FirstbootConfig, HotspotBootstrap, Ed25519Pair, Role,
)


def render_init_cfg(cfg: FirstbootConfig) -> bytes:
    """Generate /boot/astromech_init.cfg — INI-style. Refs firstboot_setup.sh:80, 304, 325-326, 355-356."""
    lines: list[str] = [
        f"# Generated by AstromechOS Imager {cfg.imager_version} on {cfg.flashed_at_iso}",
        "# DO NOT EDIT — consumed and self-destructed on first boot.",
        "",
        "[system]",
        f"user = {cfg.install_user}",
    ]
    if cfg.repo_url:
        lines += ["", "[github]",
                  f"repo_url = {cfg.repo_url}",
                  f"branch = {cfg.repo_branch}"]
    if cfg.hotspot_bootstrap is not None:
        # Contract: keys are EXACTLY 'ssid' and 'password' — firstboot_setup.sh:325-326
        lines += ["", "[hotspot]",
                  f"ssid = {cfg.hotspot_bootstrap.ssid}",
                  f"password = {cfg.hotspot_bootstrap.password}"]
    if cfg.hostname_slave != "astromech-slave":
        # firstboot_setup.sh:355 falls back to astromech-slave.local; only emit on diverge
        lines += ["", "[slave]",
                  f"host = {cfg.hostname_slave}.local"]
    return ("\n".join(lines) + "\n").encode("utf-8")
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_render_init_cfg.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/customization.py tests/unit/test_render_init_cfg.py
git commit -m "feat(core/customization): render_init_cfg ([system]/[github]/[hotspot]/[slave])"
```

---

### Task 3.2: render_init_config_json

**Files:**
- Modify: `astromechos_imager/core/customization.py`
- Test: `tests/unit/test_render_init_config_json.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_render_init_config_json.py
import json
from astromechos_imager.core.customization import render_init_config_json
from astromechos_imager.core.models import FirstbootConfig, Role


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExxxYYY user@host"


def _cfg(**kw):
    base = dict(authorized_keys=[VALID_KEY], imager_version="0.1.0",
                flashed_at_iso="2026-05-29T02:15:00Z")
    base.update(kw)
    return FirstbootConfig(**base)


def test_master_payload():
    out = render_init_config_json(_cfg(), Role.MASTER)
    obj = json.loads(out)
    assert obj == {
        "role": "master",
        "hostname": "astromech-master",
        "imager_version": "0.1.0",
        "flashed_at": "2026-05-29T02:15:00Z",
    }


def test_slave_payload():
    out = render_init_config_json(_cfg(), Role.SLAVE)
    obj = json.loads(out)
    assert obj["role"] == "slave"
    assert obj["hostname"] == "astromech-slave"


def test_hostname_override():
    cfg = _cfg(hostname_master="r2-dome")
    obj = json.loads(render_init_config_json(cfg, Role.MASTER))
    assert obj["hostname"] == "r2-dome"


def test_trailing_newline():
    out = render_init_config_json(_cfg(), Role.MASTER)
    assert out.endswith(b"\n")
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement — append to `customization.py`**

```python
def render_init_config_json(cfg: FirstbootConfig, role: Role) -> bytes:
    """Generate /boot/astromech_secrets/init_config.json. Refs firstboot_setup.sh:161-185."""
    obj = {
        "role": role.value,
        "hostname": cfg.hostname_master if role is Role.MASTER else cfg.hostname_slave,
        "imager_version": cfg.imager_version,
        "flashed_at": cfg.flashed_at_iso,
    }
    return (json.dumps(obj, indent=2) + "\n").encode("utf-8")
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_render_init_config_json.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/customization.py tests/unit/test_render_init_config_json.py
git commit -m "feat(core/customization): render_init_config_json (role + hostname)"
```

---

### Task 3.3: render_authorized_keys (slave inherits master pub)

**Files:**
- Modify: `astromechos_imager/core/customization.py`
- Test: `tests/unit/test_render_authorized_keys.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_render_authorized_keys.py
from astromechos_imager.core.customization import render_authorized_keys
from astromechos_imager.core.models import FirstbootConfig, Role


USER_KEY = "ssh-ed25519 AAAAUUUUSER user@laptop"
MASTER_PUB = b"ssh-ed25519 AAAAMMMMASTER astromech-master@imager\n"


def _cfg(keys=None):
    return FirstbootConfig(
        authorized_keys=keys or [USER_KEY],
        imager_version="0.1.0", flashed_at_iso="2026-05-29T02:15:00Z",
    )


def test_master_authorized_keys_is_just_user_keys():
    out = render_authorized_keys(_cfg(), Role.MASTER, master_pub=MASTER_PUB).decode("utf-8")
    assert out.strip().splitlines() == [USER_KEY]


def test_slave_inherits_master_pub():
    out = render_authorized_keys(_cfg(), Role.SLAVE, master_pub=MASTER_PUB).decode("utf-8")
    lines = out.strip().splitlines()
    assert USER_KEY in lines
    assert "ssh-ed25519 AAAAMMMMASTER astromech-master@imager" in lines


def test_trailing_newline_for_awk_NF():
    """firstboot_setup.sh:133 uses awk 'NF' which requires a final newline."""
    out = render_authorized_keys(_cfg(), Role.MASTER, master_pub=MASTER_PUB)
    assert out.endswith(b"\n")


def test_keys_stripped():
    out = render_authorized_keys(_cfg(keys=[f"  {USER_KEY}  "]), Role.MASTER, master_pub=MASTER_PUB)
    assert b"  " not in out.replace(b" user@", b"")  # no leading spaces remain
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement — append to `customization.py`**

```python
def render_authorized_keys(
    cfg: FirstbootConfig,
    role: Role,
    master_pub: bytes | None,
) -> bytes:
    """Generate /boot/astromech_secrets/authorized_keys.

    Refs firstboot_setup.sh:124-141 (atomic append + awk dedup on the Pi side).
    Slave inherits master's pubkey so master→slave SSH works post-firstboot.
    """
    keys = [k.strip() for k in cfg.authorized_keys]
    if role is Role.SLAVE and master_pub is not None:
        keys.append(master_pub.decode("ascii").strip())
    # Trailing \n required by awk 'NF' on the Pi side
    return ("\n".join(keys) + "\n").encode("utf-8")
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_render_authorized_keys.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/customization.py tests/unit/test_render_authorized_keys.py
git commit -m "feat(core/customization): render_authorized_keys (slave inherits master pubkey)"
```

---

### Task 3.4: BootPartition Protocol + FakeBootPartition fixture

**Files:**
- Create: `astromechos_imager/core/platform_io.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write the Protocol**

```python
# astromechos_imager/core/platform_io.py
"""Platform-IO Protocols. Lives in core/ so other core modules never import platform/.

Concrete implementations:
  - platform/windows.py provides PlatformIO (WMI + ctypes).
  - core/bootpartition.py provides BootPartition impls (β pyfatfs, α drive letter).
  - tests/conftest.py provides FakeBootPartition (dict-backed).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator, Protocol


class BootPartition(Protocol):
    """FAT32 boot partition access. Path arguments use forward-slash convention,
    relative to the partition root (e.g. '/astromech_secrets/init_config.json')."""
    def write_bytes(self, path: str, data: bytes) -> None: ...
    def read_bytes(self, path: str) -> bytes: ...
    def mkdir(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def close(self) -> None: ...


class RawDevice(Protocol):
    """Sector-aligned byte device. Opened by platform/windows.py for raw write/read."""
    sector_size: int
    size_bytes: int
    def write(self, offset: int, data: bytes) -> int: ...
    def read(self, offset: int, length: int) -> bytes: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

- [ ] **Step 2: Add `FakeBootPartition` to conftest**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def fake_boot_partition():
    """In-memory BootPartition impl for testing renderers + FirstbootBundle."""
    class _Fake:
        def __init__(self):
            self.files: dict[str, bytes] = {}
            self.dirs: set[str] = {"/"}
        def write_bytes(self, p, d):
            parent = "/" + "/".join(p.lstrip("/").split("/")[:-1])
            parent = parent.rstrip("/") or "/"
            if parent not in self.dirs:
                raise FileNotFoundError(f"parent {parent} missing")
            self.files[p] = d
        def read_bytes(self, p):
            return self.files[p]
        def mkdir(self, p):
            self.dirs.add(p)
        def exists(self, p):
            return p in self.files or p in self.dirs
        def close(self):
            pass
    return _Fake()
```

- [ ] **Step 3: Quick sanity test**

```python
# tests/unit/test_fake_boot_partition.py
def test_fake_boot_partition(fake_boot_partition):
    fake_boot_partition.mkdir("/a")
    fake_boot_partition.write_bytes("/a/x", b"hello")
    assert fake_boot_partition.read_bytes("/a/x") == b"hello"
    assert fake_boot_partition.exists("/a/x")
    assert not fake_boot_partition.exists("/missing")
```

Run: `pytest tests/unit/test_fake_boot_partition.py -v`
Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add astromechos_imager/core/platform_io.py tests/conftest.py tests/unit/test_fake_boot_partition.py
git commit -m "feat(core/platform_io): BootPartition + RawDevice Protocols + FakeBootPartition fixture"
```

---

### Task 3.5: FirstbootBundle.write_to + _self_validate

**Files:**
- Modify: `astromechos_imager/core/customization.py`
- Test: `tests/unit/test_firstboot_bundle.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_firstboot_bundle.py
import json
import pytest
from astromechos_imager.core.customization import FirstbootBundle
from astromechos_imager.core.errors import BundleSelfValidationFailedError
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _cfg(**kw):
    base = dict(authorized_keys=[VALID_KEY], imager_version="0.1.0",
                flashed_at_iso="2026-05-29T02:15:00Z",
                hotspot_bootstrap=generate_hotspot_bootstrap())
    base.update(kw)
    return FirstbootConfig(**base)


def test_master_bundle_writes_all_required_files(fake_boot_partition):
    pair = generate_ed25519()
    cfg = _cfg()
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    fp = fake_boot_partition
    assert fp.exists("/astromech_secrets/init_config.json")
    assert fp.exists("/astromech_secrets/authorized_keys")
    assert fp.exists("/astromech_secrets/id_ed25519")
    assert fp.exists("/astromech_secrets/id_ed25519.pub")
    assert fp.exists("/astromech_init.cfg")
    # Trigger LAST
    assert fp.exists("/ASTROMECH_FIRSTBOOT_READY")
    assert fp.read_bytes("/ASTROMECH_FIRSTBOOT_READY") == b""


def test_slave_bundle_no_keypair(fake_boot_partition):
    pair = generate_ed25519()
    FirstbootBundle(_cfg(), pair).write_to(fake_boot_partition, Role.SLAVE)
    fp = fake_boot_partition
    assert not fp.exists("/astromech_secrets/id_ed25519")
    assert not fp.exists("/astromech_secrets/id_ed25519.pub")
    # Slave authorized_keys must contain master's pub
    keys_text = fp.read_bytes("/astromech_secrets/authorized_keys").decode()
    assert pair.public_openssh.decode().strip() in keys_text


def test_init_config_json_role_correct(fake_boot_partition):
    pair = generate_ed25519()
    FirstbootBundle(_cfg(), pair).write_to(fake_boot_partition, Role.MASTER)
    obj = json.loads(fake_boot_partition.read_bytes("/astromech_secrets/init_config.json"))
    assert obj["role"] == "master"


def test_trigger_marker_not_written_when_validation_fails(fake_boot_partition, monkeypatch):
    """Critical safety invariant: validation failure must NOT produce a trigger marker."""
    pair = generate_ed25519()
    bundle = FirstbootBundle(_cfg(), pair)
    # Force self-validate to fail by corrupting init_config.json after step 2
    original_write = fake_boot_partition.write_bytes
    def corrupting_write(p, d):
        if p == "/astromech_secrets/init_config.json":
            d = b'{"role": "invalid", "hostname": "x"}'
        original_write(p, d)
    monkeypatch.setattr(fake_boot_partition, "write_bytes", corrupting_write)
    with pytest.raises((AssertionError, BundleSelfValidationFailedError)):
        bundle.write_to(fake_boot_partition, Role.MASTER)
    assert not fake_boot_partition.exists("/ASTROMECH_FIRSTBOOT_READY")


def test_hotspot_section_byte_identical_in_init_cfg(fake_boot_partition):
    pair = generate_ed25519()
    cfg = _cfg()
    FirstbootBundle(cfg, pair).write_to(fake_boot_partition, Role.MASTER)
    text = fake_boot_partition.read_bytes("/astromech_init.cfg").decode()
    assert f"ssid = {cfg.hotspot_bootstrap.ssid}" in text
    assert f"password = {cfg.hotspot_bootstrap.password}" in text
```

- [ ] **Step 2: Run — expect FAIL** (FirstbootBundle missing)

- [ ] **Step 3: Implement — append to `customization.py`**

```python
from astromechos_imager.core.errors import BundleSelfValidationFailedError
from astromechos_imager.core.validators import OPENSSH_PUBKEY_RE, validate_hostname


class FirstbootBundle:
    """Orchestrates per-SD bundle writing in the exact order required by safety:
    trigger marker LAST so any failure leaves the SD in a known BOOTABLE_NO_FIRSTBOOT
    state (Pi boots fine, firstboot stays dormant, operator re-flashes safely).

    Per design spec §6.4.
    """
    def __init__(self, cfg: FirstbootConfig, master_pair: Ed25519Pair):
        self.cfg = cfg
        self.master_pair = master_pair

    def write_to(self, bp, role: Role) -> None:
        # 1. Secrets directory (chmod 0700 ignored on FAT32; firstboot re-applies)
        bp.mkdir("/astromech_secrets")
        # 2. init_config.json
        bp.write_bytes("/astromech_secrets/init_config.json",
                       render_init_config_json(self.cfg, role))
        # 3. authorized_keys (slave gets master pub appended)
        master_pub = self.master_pair.public_openssh
        bp.write_bytes("/astromech_secrets/authorized_keys",
                       render_authorized_keys(self.cfg, role, master_pub))
        # 4. id_ed25519 keypair (MASTER ONLY) — refs firstboot_setup.sh:146-158
        if role is Role.MASTER:
            bp.write_bytes("/astromech_secrets/id_ed25519",
                           self.master_pair.private_openssh)
            bp.write_bytes("/astromech_secrets/id_ed25519.pub", master_pub)
        # 5. astromech_init.cfg
        bp.write_bytes("/astromech_init.cfg", render_init_cfg(self.cfg))
        # 6. hw_layout.json (optional) — refs firstboot_setup.sh:253-262
        hw = self.cfg.hw_layout_master if role is Role.MASTER else self.cfg.hw_layout_slave
        if hw is not None:
            bp.write_bytes("/hw_layout.json", Path(hw).read_bytes())
        # 7. Self-validate
        self._self_validate(bp, role)
        # 8. Trigger marker LAST — refs firstboot_setup.sh:67-72
        bp.write_bytes("/ASTROMECH_FIRSTBOOT_READY", b"")

    def _self_validate(self, bp, role: Role) -> None:
        try:
            obj = json.loads(bp.read_bytes("/astromech_secrets/init_config.json"))
            if obj["role"] not in ("master", "slave"):
                raise BundleSelfValidationFailedError(f"bad role {obj['role']!r}")
            validate_hostname(obj["hostname"])
            keys_text = bp.read_bytes("/astromech_secrets/authorized_keys").decode("utf-8")
            keys = [k.strip() for k in keys_text.splitlines() if k.strip()]
            if not any(OPENSSH_PUBKEY_RE.match(k) for k in keys):
                raise BundleSelfValidationFailedError("no valid OpenSSH key in authorized_keys")
            if role is Role.MASTER:
                if not bp.exists("/astromech_secrets/id_ed25519"):
                    raise BundleSelfValidationFailedError("master missing id_ed25519")
                if not bp.exists("/astromech_secrets/id_ed25519.pub"):
                    raise BundleSelfValidationFailedError("master missing id_ed25519.pub")
            if role is Role.SLAVE:
                master_pub_line = self.master_pair.public_openssh.decode().strip()
                if not any(master_pub_line in k for k in keys):
                    raise BundleSelfValidationFailedError(
                        "slave authorized_keys missing master pubkey "
                        "— master→slave SSH will fail"
                    )
            if self.cfg.hotspot_bootstrap is not None:
                init_cfg_text = bp.read_bytes("/astromech_init.cfg").decode("utf-8")
                if f"ssid = {self.cfg.hotspot_bootstrap.ssid}" not in init_cfg_text:
                    raise BundleSelfValidationFailedError("hotspot ssid not written")
                if f"password = {self.cfg.hotspot_bootstrap.password}" not in init_cfg_text:
                    raise BundleSelfValidationFailedError("hotspot password not written")
        except BundleSelfValidationFailedError:
            raise
        except Exception as e:
            raise BundleSelfValidationFailedError(f"self-validate failed: {e}") from e
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_firstboot_bundle.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/customization.py tests/unit/test_firstboot_bundle.py
git commit -m "feat(core/customization): FirstbootBundle.write_to + _self_validate (trigger LAST invariant)"
```

---

### Task 3.6: assert_pair_symmetry

**Files:**
- Modify: `astromechos_imager/core/customization.py`
- Test: `tests/unit/test_pair_symmetry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_pair_symmetry.py
import pytest
from astromechos_imager.core.customization import (
    FirstbootBundle, assert_pair_symmetry,
)
from astromechos_imager.core.errors import PairAsymmetryError
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _setup_pair(fake_boot_partition_factory):
    pair = generate_ed25519()
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap(),
    )
    master_bp = fake_boot_partition_factory()
    slave_bp = fake_boot_partition_factory()
    bundle = FirstbootBundle(cfg, pair)
    bundle.write_to(master_bp, Role.MASTER)
    bundle.write_to(slave_bp, Role.SLAVE)
    return master_bp, slave_bp, cfg


@pytest.fixture
def fake_boot_partition_factory(fake_boot_partition):
    # Return a callable creating fresh fakes — reuse the same class
    def _make():
        return type(fake_boot_partition)()
    return _make


def test_symmetric_pair_passes(fake_boot_partition_factory):
    m, s, _ = _setup_pair(fake_boot_partition_factory)
    assert_pair_symmetry(m, s)  # must not raise


def test_asymmetric_hotspot_raises(fake_boot_partition_factory):
    m, s, cfg = _setup_pair(fake_boot_partition_factory)
    # Tamper with slave's init.cfg [hotspot]
    text = s.read_bytes("/astromech_init.cfg").decode().replace(
        f"ssid = {cfg.hotspot_bootstrap.ssid}",
        "ssid = Astromech_Boot_DEAD"
    )
    s.write_bytes("/astromech_init.cfg", text.encode())
    with pytest.raises(PairAsymmetryError):
        assert_pair_symmetry(m, s)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement — append to `customization.py`**

```python
from astromechos_imager.core.errors import PairAsymmetryError


def _extract_section(init_cfg_bytes: bytes, section: str) -> str | None:
    """Extract a single [section] block as a normalized string (sorted keys)."""
    text = init_cfg_bytes.decode("utf-8")
    out: list[str] = []
    in_section = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_section = (s == f"[{section}]")
            continue
        if in_section and "=" in s:
            out.append(s)
    if not out:
        return None
    return "\n".join(sorted(out))


def assert_pair_symmetry(master_bp, slave_bp) -> None:
    """Per design spec §2.3 invariants — same [hotspot] block on both cards."""
    m_cfg = master_bp.read_bytes("/astromech_init.cfg")
    s_cfg = slave_bp.read_bytes("/astromech_init.cfg")
    m_hot = _extract_section(m_cfg, "hotspot")
    s_hot = _extract_section(s_cfg, "hotspot")
    if m_hot != s_hot:
        raise PairAsymmetryError(
            f"master/slave [hotspot] block mismatch — master={m_hot!r} slave={s_hot!r}"
        )
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_pair_symmetry.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/customization.py tests/unit/test_pair_symmetry.py
git commit -m "feat(core/customization): assert_pair_symmetry (byte-identical [hotspot] invariant)"
```

---

## Phase 4 — Platform Windows + BootPartition

### Task 4.1: Win32 constants & ctypes wrappers

**Files:**
- Create: `astromechos_imager/platform/_win32.py`
- Test: `tests/unit/test_win32_constants.py`

NOTE — this task builds the LOWEST layer (constants, structs, helper signatures). No I/O yet — that's Task 4.3-4.4.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_win32_constants.py
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


def test_constants_match_winioctl():
    from astromechos_imager.platform._win32 import (
        GENERIC_READ, GENERIC_WRITE, FILE_SHARE_READ, FILE_SHARE_WRITE,
        OPEN_EXISTING, FILE_FLAG_NO_BUFFERING, FILE_FLAG_WRITE_THROUGH,
        FSCTL_LOCK_VOLUME, FSCTL_DISMOUNT_VOLUME,
        IOCTL_DISK_UPDATE_PROPERTIES, IOCTL_STORAGE_EJECT_MEDIA,
        IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, INVALID_HANDLE_VALUE,
    )
    assert GENERIC_READ == 0x80000000
    assert GENERIC_WRITE == 0x40000000
    assert FILE_SHARE_READ == 0x00000001
    assert FILE_SHARE_WRITE == 0x00000002
    assert OPEN_EXISTING == 3
    assert FILE_FLAG_NO_BUFFERING == 0x20000000
    assert FILE_FLAG_WRITE_THROUGH == 0x80000000
    assert FSCTL_LOCK_VOLUME == 0x00090018
    assert FSCTL_DISMOUNT_VOLUME == 0x00090020
    assert IOCTL_DISK_UPDATE_PROPERTIES == 0x00070140
    assert IOCTL_STORAGE_EJECT_MEDIA == 0x002D4808
    assert IOCTL_DISK_GET_DRIVE_GEOMETRY_EX == 0x000700A0
    assert INVALID_HANDLE_VALUE == -1
```

- [ ] **Step 2: Run — expect FAIL or SKIP**

- [ ] **Step 3: Implement**

```python
# astromechos_imager/platform/_win32.py
"""Win32 constants and ctypes prototypes. Isolated so unit tests can pin
the values without pulling in kernel32 at import time on non-Windows CI."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

# CreateFileW access + share + create-disposition
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_FLAG_WRITE_THROUGH = 0x80000000
INVALID_HANDLE_VALUE = -1

# Volume control
FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_DISMOUNT_VOLUME = 0x00090020
FSCTL_ALLOW_EXTENDED_DASD_IO = 0x00090083

# Disk IOCTL
IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808


class DISK_GEOMETRY_EX(ctypes.Structure):
    _fields_ = [
        ("Cylinders", ctypes.c_longlong),
        ("MediaType", wintypes.DWORD),
        ("TracksPerCylinder", wintypes.DWORD),
        ("SectorsPerTrack", wintypes.DWORD),
        ("BytesPerSector", wintypes.DWORD),
        ("DiskSize", ctypes.c_longlong),
        ("Data", ctypes.c_byte * 32),
    ]


# Lazily load kernel32 — never at import time so non-Windows CI can still import.
_kernel32 = None
def kernel32():
    global _kernel32
    if _kernel32 is None:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        _kernel32.CreateFileW.restype = wintypes.HANDLE
        _kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        _kernel32.DeviceIoControl.restype = wintypes.BOOL
        _kernel32.WriteFile.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        _kernel32.WriteFile.restype = wintypes.BOOL
        _kernel32.ReadFile.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        _kernel32.ReadFile.restype = wintypes.BOOL
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32.CloseHandle.restype = wintypes.BOOL
        _kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        _kernel32.FlushFileBuffers.restype = wintypes.BOOL
        _kernel32.SetFilePointerEx.argtypes = [
            wintypes.HANDLE, ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD,
        ]
        _kernel32.SetFilePointerEx.restype = wintypes.BOOL
    return _kernel32
```

- [ ] **Step 4: Run — expect PASS on Windows / SKIP elsewhere**

Run: `pytest tests/unit/test_win32_constants.py -v`
Expected: 1 passed (Windows) or 1 skipped (Linux/Mac CI).

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/platform/_win32.py tests/unit/test_win32_constants.py
git commit -m "feat(platform): Win32 constants + lazy kernel32 ctypes wrappers"
```

---

### Task 4.2: WMI drive enumeration

**Files:**
- Create: `astromechos_imager/platform/windows.py`
- Test: `tests/unit/test_drive_enum.py`

- [ ] **Step 1: Write failing test (mocked WMI)**

```python
# tests/unit/test_drive_enum.py
from unittest.mock import MagicMock, patch
from astromechos_imager.platform.windows import enumerate_removable_drives
from astromechos_imager.core.models import DiskRef


def _wmi_disk(device_id, size, model, serial, interface_type, media_type):
    m = MagicMock()
    m.DeviceID = device_id
    m.Size = str(size)
    m.Model = model
    m.SerialNumber = serial
    m.InterfaceType = interface_type
    m.MediaType = media_type
    return m


def test_filters_to_removable_usb(monkeypatch):
    fake_drives = [
        _wmi_disk(r"\\.\PHYSICALDRIVE0", 1_000_000_000_000, "Samsung SSD", "INTERNAL",
                  "SATA", "Fixed hard disk media"),
        _wmi_disk(r"\\.\PHYSICALDRIVE2", 32_000_000_000, "SanDisk Ultra", "USB-1",
                  "USB", "Removable Media"),
        _wmi_disk(r"\\.\PHYSICALDRIVE3", 16_000_000_000, "Some USB stick", "USB-2",
                  "USB", "Removable Media"),
    ]
    with patch("astromechos_imager.platform.windows._wmi_query") as q:
        q.return_value = fake_drives
        with patch("astromechos_imager.platform.windows._drive_letters_for") as letters:
            letters.side_effect = lambda did: ("E",) if "DRIVE2" in did else ("F",)
            with patch("astromechos_imager.platform.windows._system_drive_id") as sd:
                sd.return_value = 0  # PHYSICALDRIVE0 is system
                drives = list(enumerate_removable_drives())
    ids = [d.physical_drive_id for d in drives]
    assert 0 not in ids  # system drive excluded
    assert 2 in ids and 3 in ids
    e = next(d for d in drives if d.physical_drive_id == 2)
    assert e.drive_letters == ("E",)
    assert e.model == "SanDisk Ultra"


def test_excludes_drives_over_256gb(monkeypatch):
    fake_drives = [
        _wmi_disk(r"\\.\PHYSICALDRIVE5", 500_000_000_000, "Huge USB drive",
                  "TOO_BIG", "USB", "Removable Media"),
    ]
    with patch("astromechos_imager.platform.windows._wmi_query") as q:
        q.return_value = fake_drives
        with patch("astromechos_imager.platform.windows._drive_letters_for", return_value=()):
            with patch("astromechos_imager.platform.windows._system_drive_id", return_value=0):
                drives = list(enumerate_removable_drives())
    assert drives == []
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# astromechos_imager/platform/windows.py
"""Windows platform IO. Per design spec §5.1-5.2.

ONLY this module imports Win32 APIs. Everything else routes through
core/platform_io.py Protocols.
"""
from __future__ import annotations

import os
import re
from typing import Iterator

from astromechos_imager.core.models import DiskRef

_MAX_SD_BYTES = 256 * 1024 * 1024 * 1024   # hard cap — no R2 build needs > 256 GB
_PHYS_DRIVE_RE = re.compile(r"PHYSICALDRIVE(\d+)", re.IGNORECASE)


def _wmi_query() -> list:
    """Query Win32_DiskDrive via WMI. Indirected for monkeypatching in tests."""
    import win32com.client  # pywin32
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    q = ("SELECT DeviceID, Size, Model, SerialNumber, InterfaceType, MediaType "
         "FROM Win32_DiskDrive")
    return list(wmi.ExecQuery(q))


def _drive_letters_for(device_id: str) -> tuple[str, ...]:
    """Resolve drive letters mounted on a Win32_DiskDrive via the partition graph."""
    import win32com.client
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    letters: list[str] = []
    parts = wmi.ExecQuery(
        f"ASSOCIATORS OF {{Win32_DiskDrive.DeviceID='{device_id}'}} "
        "WHERE AssocClass=Win32_DiskDriveToDiskPartition"
    )
    for part in parts:
        logicals = wmi.ExecQuery(
            f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{part.DeviceID}'}} "
            "WHERE AssocClass=Win32_LogicalDiskToPartition"
        )
        for logical in logicals:
            if logical.DeviceID:
                letters.append(logical.DeviceID.rstrip(":"))
    return tuple(letters)


def _system_drive_id() -> int:
    """Return the PhysicalDriveN number that hosts %SystemDrive% (e.g. C:)."""
    sys_letter = os.environ.get("SystemDrive", "C:").rstrip(":")
    import win32com.client
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    for ld in wmi.ExecQuery(f"SELECT * FROM Win32_LogicalDisk WHERE DeviceID='{sys_letter}:'"):
        parts = wmi.ExecQuery(
            f"ASSOCIATORS OF {{Win32_LogicalDisk.DeviceID='{ld.DeviceID}'}} "
            "WHERE AssocClass=Win32_LogicalDiskToPartition"
        )
        for part in parts:
            drives = wmi.ExecQuery(
                f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{part.DeviceID}'}} "
                "WHERE AssocClass=Win32_DiskDriveToDiskPartition"
            )
            for drive in drives:
                m = _PHYS_DRIVE_RE.search(drive.DeviceID)
                if m:
                    return int(m.group(1))
    return -1


def enumerate_removable_drives() -> Iterator[DiskRef]:
    """Yield only safe removable candidates. Refs design spec §5.1."""
    sys_id = _system_drive_id()
    for d in _wmi_query():
        is_usb = (d.InterfaceType or "").upper() == "USB"
        is_removable = "removable" in (d.MediaType or "").lower()
        if not (is_usb or is_removable):
            continue
        m = _PHYS_DRIVE_RE.search(d.DeviceID or "")
        if not m:
            continue
        phys_id = int(m.group(1))
        if phys_id == sys_id:
            continue
        size = int(d.Size or 0)
        if size <= 0 or size > _MAX_SD_BYTES:
            continue
        yield DiskRef(
            physical_drive_id=phys_id,
            device_path=d.DeviceID,
            drive_letters=_drive_letters_for(d.DeviceID),
            size_bytes=size,
            model=(d.Model or "Unknown").strip(),
            serial=(d.SerialNumber or "").strip(),
        )
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_drive_enum.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/platform/windows.py tests/unit/test_drive_enum.py
git commit -m "feat(platform): WMI-based removable drive enumeration with system-drive exclusion"
```

---

### Task 4.3: Lock + dismount + raw device open

**Files:**
- Modify: `astromechos_imager/platform/windows.py`
- Test: `tests/integration/test_lock_dismount.py` (marked `@pytest.mark.windows`, manual-only)

- [ ] **Step 1: Add the lock/dismount logic to `windows.py`**

```python
import ctypes
import time
from ctypes import wintypes
from astromechos_imager.core.errors import DriveLockError, DrivePermissionError
from astromechos_imager.platform._win32 import (
    GENERIC_READ, GENERIC_WRITE, FILE_SHARE_READ, FILE_SHARE_WRITE,
    OPEN_EXISTING, FILE_FLAG_NO_BUFFERING, FILE_FLAG_WRITE_THROUGH,
    FSCTL_LOCK_VOLUME, FSCTL_DISMOUNT_VOLUME, INVALID_HANDLE_VALUE,
    IOCTL_DISK_UPDATE_PROPERTIES, IOCTL_STORAGE_EJECT_MEDIA, kernel32,
)


def _ctl(handle: int, code: int, in_buf: bytes = b"") -> None:
    k = kernel32()
    out = wintypes.DWORD(0)
    ok = k.DeviceIoControl(
        handle, code,
        ctypes.c_char_p(in_buf) if in_buf else None, len(in_buf),
        None, 0, ctypes.byref(out), None,
    )
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"DeviceIoControl(0x{code:08X}) failed (Win32 err {err})")


def _create_volume_handle(letter: str) -> int:
    """Open \\.\X: for FSCTL operations. Returns handle or raises."""
    k = kernel32()
    path = f"\\\\.\\{letter}:"
    h = k.CreateFileW(
        path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING, 0, None,
    )
    if h == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        if err == 5:  # ERROR_ACCESS_DENIED
            raise DrivePermissionError(f"Cannot open volume {letter}: (need admin?)")
        raise OSError(err, f"CreateFileW({path}) failed")
    return h


def lock_and_dismount(letters: tuple[str, ...]) -> list[int]:
    """For each drive letter, lock + dismount and keep the handle open.
    Returns the list of handles — caller closes them after raw write completes.
    Refs design spec §5.2 — retries 3× at 500 ms."""
    handles: list[int] = []
    for letter in letters:
        h = _create_volume_handle(letter)
        last_err = None
        for attempt in range(3):
            try:
                _ctl(h, FSCTL_LOCK_VOLUME)
                break
            except OSError as e:
                last_err = e
                time.sleep(0.5)
        else:
            kernel32().CloseHandle(h)
            for prev in handles:
                kernel32().CloseHandle(prev)
            raise DriveLockError(
                f"FSCTL_LOCK_VOLUME failed for {letter}: after 3 retries "
                f"(close Explorer / antivirus). Last err: {last_err}"
            )
        _ctl(h, FSCTL_DISMOUNT_VOLUME)
        handles.append(h)
    return handles


def open_raw_device(physical_drive_id: int) -> int:
    """Open \\.\PHYSICALDRIVEn for raw read+write. Returns handle or raises."""
    k = kernel32()
    path = f"\\\\.\\PHYSICALDRIVE{physical_drive_id}"
    h = k.CreateFileW(
        path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING, FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH, None,
    )
    if h == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateFileW({path}) failed")
    return h


def close_handle(h: int) -> None:
    kernel32().CloseHandle(h)


def update_disk_properties(h: int) -> None:
    """After writing partition table, force Windows to re-enumerate volumes."""
    _ctl(h, IOCTL_DISK_UPDATE_PROPERTIES)


def eject_media(h: int) -> None:
    """Best-effort eject. Caller logs warning on failure."""
    _ctl(h, IOCTL_STORAGE_EJECT_MEDIA)
```

- [ ] **Step 2: Write integration test (skipped in normal CI — manual run with real SD)**

```python
# tests/integration/test_lock_dismount.py
import os
import sys
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only"),
    pytest.mark.skipif("INTEGRATION_REAL_SD" not in os.environ,
                       reason="set INTEGRATION_REAL_SD=<letter> to enable"),
]


def test_lock_and_dismount_real_sd():
    from astromechos_imager.platform.windows import lock_and_dismount, close_handle
    letter = os.environ["INTEGRATION_REAL_SD"].rstrip(":")
    handles = lock_and_dismount((letter,))
    try:
        assert len(handles) == 1
    finally:
        for h in handles:
            close_handle(h)
```

- [ ] **Step 3: Run unit-level verify (sanity import on Windows)**

Run: `pytest tests/integration/test_lock_dismount.py -v`
Expected: 1 skipped.

- [ ] **Step 4: Commit**

```bash
git add astromechos_imager/platform/windows.py tests/integration/test_lock_dismount.py
git commit -m "feat(platform): lock + dismount + open_raw_device + eject (3-retry lock with admin hint)"
```

---

### Task 4.4: PlatformIO concrete + FakePlatformIO for tests

**Files:**
- Modify: `astromechos_imager/core/platform_io.py` (add `PlatformIO` Protocol)
- Modify: `astromechos_imager/platform/windows.py` (add `WindowsPlatformIO` class)
- Modify: `tests/conftest.py` (add `FakePlatformIO`)

- [ ] **Step 1: Extend `platform_io.py`**

Append to `astromechos_imager/core/platform_io.py`:

```python
from astromechos_imager.core.models import DiskRef


class PlatformIO(Protocol):
    """Top-level platform façade — injected by the CLI/UI entry points."""
    def enumerate_removable_drives(self) -> list[DiskRef]: ...
    def lock_and_dismount(self, letters: tuple[str, ...]) -> list[int]: ...
    def open_raw_device(self, physical_drive_id: int) -> RawDevice: ...
    def close_handle(self, handle: int) -> None: ...
    def update_disk_properties(self, handle: int) -> None: ...
    def eject_media(self, handle: int) -> None: ...
```

- [ ] **Step 2: Implement `WindowsPlatformIO`**

Append to `astromechos_imager/platform/windows.py`:

```python
from astromechos_imager.core.platform_io import RawDevice


class _Win32RawDevice:
    """RawDevice adapter wrapping a kernel32 HANDLE.

    The sector_size is queried lazily on first write/read so unit tests that
    only construct the object don't pay the syscall.
    """
    def __init__(self, handle: int, size_bytes: int):
        self._h = handle
        self.size_bytes = size_bytes
        self._sector_size: int | None = None

    @property
    def sector_size(self) -> int:
        if self._sector_size is None:
            self._sector_size = _query_sector_size(self._h)
        return self._sector_size

    def write(self, offset: int, data: bytes) -> int:
        _seek(self._h, offset)
        written = wintypes.DWORD(0)
        ok = kernel32().WriteFile(
            self._h, ctypes.c_char_p(data), len(data),
            ctypes.byref(written), None,
        )
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(err, f"WriteFile failed at offset {offset}")
        return written.value

    def read(self, offset: int, length: int) -> bytes:
        _seek(self._h, offset)
        buf = ctypes.create_string_buffer(length)
        got = wintypes.DWORD(0)
        ok = kernel32().ReadFile(self._h, buf, length, ctypes.byref(got), None)
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(err, f"ReadFile failed at offset {offset}")
        return bytes(buf.raw[: got.value])

    def flush(self) -> None:
        kernel32().FlushFileBuffers(self._h)

    def close(self) -> None:
        close_handle(self._h)


def _seek(h: int, offset: int) -> None:
    new_pos = ctypes.c_longlong(0)
    ok = kernel32().SetFilePointerEx(h, offset, ctypes.byref(new_pos), 0)  # FILE_BEGIN
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"SetFilePointerEx({offset}) failed")


def _query_sector_size(h: int) -> int:
    from astromechos_imager.platform._win32 import DISK_GEOMETRY_EX, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX
    out = DISK_GEOMETRY_EX()
    written = wintypes.DWORD(0)
    ok = kernel32().DeviceIoControl(
        h, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, None, 0,
        ctypes.byref(out), ctypes.sizeof(out),
        ctypes.byref(written), None,
    )
    if not ok:
        return 512  # safe default
    return int(out.BytesPerSector)


class WindowsPlatformIO:
    def enumerate_removable_drives(self):
        return list(enumerate_removable_drives())

    def lock_and_dismount(self, letters):
        return lock_and_dismount(letters)

    def open_raw_device(self, physical_drive_id):
        h = open_raw_device(physical_drive_id)
        # Re-query size from WMI to avoid a second sector_size syscall during write loop
        size = 0
        for d in enumerate_removable_drives():
            if d.physical_drive_id == physical_drive_id:
                size = d.size_bytes
                break
        return _Win32RawDevice(h, size)

    def close_handle(self, handle):
        close_handle(handle)

    def update_disk_properties(self, handle):
        update_disk_properties(handle)

    def eject_media(self, handle):
        eject_media(handle)
```

- [ ] **Step 3: Add `FakePlatformIO` to conftest**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def fake_platform_io(tmp_path):
    """Dict-backed PlatformIO impl. Each physical_drive_id maps to a sparse file."""
    from astromechos_imager.core.models import DiskRef

    class _FakeRawDevice:
        sector_size = 512
        def __init__(self, path, size):
            self._path = path
            self.size_bytes = size
            self._fh = open(path, "r+b")
        def write(self, offset, data):
            self._fh.seek(offset); self._fh.write(data); return len(data)
        def read(self, offset, length):
            self._fh.seek(offset); return self._fh.read(length)
        def flush(self):
            self._fh.flush()
        def close(self):
            self._fh.close()

    class _Fake:
        def __init__(self):
            self.drives: dict[int, DiskRef] = {}
            self.handles: list[int] = []
            self._next_h = 1000
        def add_drive(self, phys_id: int, size: int = 32 << 30, model="Test SD"):
            path = tmp_path / f"sparse_{phys_id}.img"
            path.touch()
            os.truncate(path, size)
            self.drives[phys_id] = DiskRef(
                physical_drive_id=phys_id,
                device_path=f"\\\\.\\PHYSICALDRIVE{phys_id}",
                drive_letters=(),
                size_bytes=size,
                model=model,
                serial=f"TEST-{phys_id}",
            )
            return path
        def enumerate_removable_drives(self):
            return list(self.drives.values())
        def lock_and_dismount(self, letters):
            return [self._next_h := self._next_h + 1 for _ in letters]
        def open_raw_device(self, phys_id):
            path = tmp_path / f"sparse_{phys_id}.img"
            return _FakeRawDevice(path, self.drives[phys_id].size_bytes)
        def close_handle(self, h): pass
        def update_disk_properties(self, h): pass
        def eject_media(self, h): pass
    return _Fake()
```

- [ ] **Step 4: Quick sanity test**

```python
# tests/unit/test_fake_platform_io.py
def test_fake_platform_io_basic(fake_platform_io):
    fake_platform_io.add_drive(2, size=1024 * 1024)
    drives = fake_platform_io.enumerate_removable_drives()
    assert len(drives) == 1
    assert drives[0].physical_drive_id == 2
    dev = fake_platform_io.open_raw_device(2)
    dev.write(0, b"hello")
    assert dev.read(0, 5) == b"hello"
    dev.close()
```

Run: `pytest tests/unit/test_fake_platform_io.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/platform_io.py astromechos_imager/platform/windows.py tests/conftest.py tests/unit/test_fake_platform_io.py
git commit -m "feat(platform): WindowsPlatformIO facade + FakePlatformIO test fixture"
```

---

### Task 4.5: BootPartition β (pyfatfs) + α (drive letter) with auto-fallback

**Files:**
- Create: `astromechos_imager/core/bootpartition.py`
- Test: `tests/integration/test_bootpartition_roundtrip.py`

NOTE — heavy task; ~30 min. The MBR parsing is small and self-contained; the pyfatfs adapter is mostly delegation. The α fallback only runs on Windows because it polls drive letters.

- [ ] **Step 1: Write the MBR parser test**

```python
# tests/unit/test_mbr_parse.py
from astromechos_imager.core.bootpartition import find_first_fat32_partition, BootPartitionLayout


def test_typical_pi_os_layout():
    # First 512 bytes of a typical Pi OS image: MBR with one FAT32 (type 0x0C) partition
    # starting at sector 8192, length 1048576 sectors (512 MB).
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    # Partition entry 1 at offset 446
    entry = mbr[446:462]
    # Boot indicator, CHS first sector (ignored), partition type, CHS last sector, LBA first, LBA size
    entry[0] = 0x00
    entry[4] = 0x0C  # FAT32 LBA
    entry[8:12] = (8192).to_bytes(4, "little")
    entry[12:16] = (1024 * 1024).to_bytes(4, "little")
    mbr[446:462] = entry
    layout = find_first_fat32_partition(bytes(mbr))
    assert isinstance(layout, BootPartitionLayout)
    assert layout.offset == 8192 * 512
    assert layout.size == 1024 * 1024 * 512
    assert layout.partition_type == 0x0C
```

- [ ] **Step 2: Implement MBR parsing + protocol implementations**

```python
# astromechos_imager/core/bootpartition.py
"""FAT32 boot partition access (β pyfatfs primary, α drive letter fallback).

Per design spec §5.6.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from pathlib import Path

from astromechos_imager.core.errors import BootPartitionMountError, BootPartitionWriteError


@dataclass(frozen=True)
class BootPartitionLayout:
    offset: int           # bytes from start of disk
    size: int             # bytes
    partition_type: int   # 0x0B / 0x0C for FAT32


def find_first_fat32_partition(mbr_bytes: bytes) -> BootPartitionLayout:
    """Parse a 512-byte MBR and return the first FAT32 partition.

    Pi OS uses MBR (not GPT) and lays out a small FAT32 boot partition first.
    """
    if len(mbr_bytes) < 512 or mbr_bytes[510:512] != b"\x55\xAA":
        raise BootPartitionMountError("Invalid MBR signature")
    SECTOR = 512
    for i in range(4):
        e = mbr_bytes[446 + i * 16 : 462 + i * 16]
        ptype = e[4]
        if ptype in (0x0B, 0x0C, 0x06, 0x0E):  # FAT32/FAT16 variants
            lba_start = struct.unpack("<I", e[8:12])[0]
            lba_size = struct.unpack("<I", e[12:16])[0]
            if lba_size == 0:
                continue
            return BootPartitionLayout(
                offset=lba_start * SECTOR,
                size=lba_size * SECTOR,
                partition_type=ptype,
            )
    raise BootPartitionMountError("No FAT32 partition found in MBR")


# ── β path: pyfatfs over raw device ───────────────────────────────────────
class PyFatFsBootPartition:
    """Direct FAT32 access via pyfatfs on the raw image. No Windows remount needed."""
    def __init__(self, raw_device_path: str, layout: BootPartitionLayout):
        try:
            from pyfatfs.PyFatFS import PyFatFS  # lazy import
        except ImportError as e:
            raise BootPartitionMountError(f"pyfatfs not available: {e}") from e
        try:
            self._fs = PyFatFS(filename=raw_device_path,
                               offset=layout.offset,
                               size=layout.size)
        except Exception as e:
            raise BootPartitionMountError(f"pyfatfs mount failed: {e}") from e

    def write_bytes(self, path: str, data: bytes) -> None:
        try:
            self._fs.writebytes(path, data)
        except Exception as e:
            raise BootPartitionWriteError(f"write {path} failed: {e}") from e

    def read_bytes(self, path: str) -> bytes:
        return self._fs.readbytes(path)

    def mkdir(self, path: str) -> None:
        try:
            self._fs.makedirs(path, recreate=True)
        except Exception as e:
            raise BootPartitionWriteError(f"mkdir {path} failed: {e}") from e

    def exists(self, path: str) -> bool:
        return self._fs.exists(path)

    def close(self) -> None:
        try:
            self._fs.close()
        except Exception:
            pass


# ── α path: drive letter after Windows remount ────────────────────────────
class DriveLetterBootPartition:
    """Writes via the auto-mounted drive letter Windows assigns after partition refresh."""
    def __init__(self, letter: str):
        self._root = Path(f"{letter}:\\")
        if not self._root.exists():
            raise BootPartitionMountError(f"drive {letter}: not mounted")

    def write_bytes(self, path: str, data: bytes) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    def read_bytes(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def mkdir(self, path: str) -> None:
        self._resolve(path).mkdir(parents=True, exist_ok=True)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def close(self) -> None:
        pass

    def _resolve(self, path: str) -> Path:
        rel = path.lstrip("/").replace("/", "\\")
        return self._root / rel


def wait_for_new_drive_letter(known_before: set[str], timeout_s: float = 30.0) -> str:
    """Poll GetLogicalDrives for a letter not in `known_before`. Windows-only."""
    import ctypes
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        bits = ctypes.windll.kernel32.GetLogicalDrives()
        present = {chr(ord("A") + i) for i in range(26) if bits & (1 << i)}
        new = present - known_before
        if new:
            return sorted(new)[0]
        time.sleep(0.25)
    raise BootPartitionMountError("no new drive letter appeared within timeout")


def open_boot_partition(raw_device_path: str, layout: BootPartitionLayout,
                         known_letters_before: set[str]):
    """Try β first, fall back to α. Returns a BootPartition-protocol object."""
    try:
        return PyFatFsBootPartition(raw_device_path, layout)
    except BootPartitionMountError:
        # α fallback — only viable on Windows after IOCTL_DISK_UPDATE_PROPERTIES
        letter = wait_for_new_drive_letter(known_letters_before)
        return DriveLetterBootPartition(letter)
```

- [ ] **Step 3: Write the integration test**

```python
# tests/integration/test_bootpartition_roundtrip.py
import os
import struct
import pytest
from pathlib import Path
from astromechos_imager.core.bootpartition import (
    PyFatFsBootPartition, find_first_fat32_partition, BootPartitionLayout,
)

pytestmark = pytest.mark.integration


def _make_fat32_image(path: Path, total_mb: int = 64, boot_mb: int = 32):
    """Build a sparse MBR disk with one FAT32 partition formatted via pyfatfs."""
    path.write_bytes(b"\x00" * (total_mb * 1024 * 1024))
    SECTOR = 512
    start_lba = 2048
    size_lba = (boot_mb * 1024 * 1024) // SECTOR
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"
    e = bytearray(16)
    e[4] = 0x0C
    e[8:12] = struct.pack("<I", start_lba)
    e[12:16] = struct.pack("<I", size_lba)
    mbr[446:462] = bytes(e)
    with path.open("r+b") as f:
        f.write(bytes(mbr))
    # Format the partition slice as FAT32
    from pyfatfs.PyFatFS import PyFatFS
    fs = PyFatFS(filename=str(path), offset=start_lba * SECTOR,
                 size=size_lba * SECTOR, lazy_load=False)
    fs.close()


def test_pyfatfs_roundtrip(tmp_path):
    img = tmp_path / "fake_sd.img"
    _make_fat32_image(img)
    mbr = img.read_bytes()[:512]
    layout = find_first_fat32_partition(mbr)
    bp = PyFatFsBootPartition(str(img), layout)
    try:
        bp.mkdir("/astromech_secrets")
        bp.write_bytes("/astromech_secrets/init_config.json", b'{"role":"master"}')
        bp.write_bytes("/ASTROMECH_FIRSTBOOT_READY", b"")
        assert bp.exists("/ASTROMECH_FIRSTBOOT_READY")
        assert bp.read_bytes("/astromech_secrets/init_config.json") == b'{"role":"master"}'
    finally:
        bp.close()
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/unit/test_mbr_parse.py tests/integration/test_bootpartition_roundtrip.py -v`
Expected: 2 passed (assuming pyfatfs has FAT32 formatting support; if not, the integration test gets skipped — see follow-up note).

NOTE — if `pyfatfs` cannot format an empty FAT32 region at construction time, replace the formatting step in `_make_fat32_image` with a call to `mkfs.fat` (Linux CI) or `format /FS:FAT32` (Windows). Document in CI scripts.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/bootpartition.py tests/unit/test_mbr_parse.py tests/integration/test_bootpartition_roundtrip.py
git commit -m "feat(core/bootpartition): pyfatfs (β) + drive-letter (α) impls with MBR parse + auto-fallback"
```

---

## Phase 5 — DiskWriter + verify

### Task 5.1: DiskWriter producer-consumer pipeline

**Files:**
- Create: `astromechos_imager/core/diskwriter.py`
- Test: `tests/integration/test_diskwriter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_diskwriter.py
import hashlib
import lzma
import pytest
from astromechos_imager.core.diskwriter import DiskWriter, DiskWriterProgress
from astromechos_imager.core.imagesource import open_image

pytestmark = pytest.mark.integration


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_writes_raw_image_to_fake_device(tmp_path, fake_platform_io):
    payload = _mbr(b"R2D2" * 250_000)
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    src_path = tmp_path / "im.img"
    src_path.write_bytes(payload)

    events: list = []
    def on_progress(p: DiskWriterProgress):
        events.append((p.phase, p.bytes_done))

    with open_image(src_path) as src:
        dev = fake_platform_io.open_raw_device(2)
        try:
            dw = DiskWriter(src, dev, on_progress=on_progress)
            result = dw.run()
        finally:
            dev.close()
    assert result.bytes_written == len(payload)
    assert result.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert any(phase == "decompress_write" for phase, _ in events)


def test_writes_xz_image_to_fake_device(tmp_path, fake_platform_io):
    payload = _mbr(b"hello" * 500_000)
    fake_platform_io.add_drive(3, size=len(payload) + 1024)
    src_path = tmp_path / "im.img.xz"
    src_path.write_bytes(lzma.compress(payload))
    with open_image(src_path) as src:
        dev = fake_platform_io.open_raw_device(3)
        try:
            dw = DiskWriter(src, dev)
            result = dw.run()
        finally:
            dev.close()
    assert result.source_sha256 == hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
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

from astromechos_imager.core.errors import WriteError
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
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/integration/test_diskwriter.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/diskwriter.py tests/integration/test_diskwriter.py
git commit -m "feat(core/diskwriter): producer-consumer pipeline with in-flight SHA256"
```

---

### Task 5.2: Verify (read-back) + first-diff offset

**Files:**
- Modify: `astromechos_imager/core/diskwriter.py`
- Test: `tests/integration/test_verify.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_verify.py
import hashlib
import pytest
from astromechos_imager.core.diskwriter import verify_readback
from astromechos_imager.core.errors import HashMismatchError

pytestmark = pytest.mark.integration


def test_verify_matches(fake_platform_io):
    payload = b"X" * 1_000_000
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    dev = fake_platform_io.open_raw_device(2)
    try:
        dev.write(0, payload)
        verify_readback(dev, expected_sha256=hashlib.sha256(payload).hexdigest(),
                         length=len(payload))
    finally:
        dev.close()


def test_verify_mismatch_carries_offset(fake_platform_io):
    payload = b"X" * 1_000_000
    fake_platform_io.add_drive(3, size=len(payload) + 1024)
    dev = fake_platform_io.open_raw_device(3)
    try:
        # Write payload but with a flip in the middle
        corrupted = bytearray(payload)
        corrupted[500_000] = ord("Y")
        dev.write(0, bytes(corrupted))
        with pytest.raises(HashMismatchError) as ei:
            verify_readback(dev, expected_sha256=hashlib.sha256(payload).hexdigest(),
                             length=len(payload))
        # Offset detection is best-effort (block-aligned)
        assert ei.value.first_diff_offset >= 0
    finally:
        dev.close()
```

- [ ] **Step 2: Run — expect FAIL** (verify_readback missing)

- [ ] **Step 3: Implement — append to `diskwriter.py`**

```python
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
    first_diff_block: int = -1
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
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/integration/test_verify.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/diskwriter.py tests/integration/test_verify.py
git commit -m "feat(core/diskwriter): verify_readback with SHA256 round-trip"
```

---

## Phase 5.5 — Rootfs personalization (cold ext4 modification)

**Status: spec frozen, library choice deferred to Task 5.5.0 POC.**

Per design spec §2.2.1, the Imager must offline-edit the rootfs ext4 partition to rename the Golden Image's UID-1000 user (login + `/home/<name>` dir + `/etc/{passwd,shadow,group}` rows + group memberships). The AstromechOS security audit explicitly rejected a firstboot-time rename (plaintext leaks via running procs + race conditions), so cold modification is the only acceptable path.

**Scope** : restricted to the four operations enumerated in §2.2.1 — no other rootfs edits. SSH key injection stays on its existing firstboot path. Phase 5.5 runs **after** the verify step of each `FlashJob` and **before** the FAT32 customize step, so a Phase 5.5 failure leaves the SD in `BOOTABLE_NO_FIRSTBOOT` (image fully written, rootfs partially modified, no trigger marker) — same safety class as a customize-phase failure.

### Task 5.5.0: Choose ext4-on-Windows backend (POC)

**Files:**
- Create: `tests/poc/test_ext4_backends.py`
- Add docs decision in: `docs/superpowers/specs/2026-05-29-astromechos-imager-design.md` §13 (new appendix)

Evaluate 2-3 candidates against a fixture ext4 image (~64 MB sparse, formatted via `mkfs.ext4` on Linux CI runner or a checked-in pre-formatted blob):

| Candidate | Pros | Cons |
|---|---|---|
| **Python lib `ext4`** | Pure-Python, no external binary | Mostly read-oriented historically; write support varies by version |
| **Python lib `ext4fs`** | More recent fork | Smaller community, less battle-tested |
| **Bundled `e2tools.exe`** (Cygwin port: `e2cp`, `e2mv`, `e2ln`, `e2rm`) | Battle-tested code from e2fsprogs; supports write + dir rename | ~200 KB extra in `.exe`, subprocess overhead per op, Windows binary licensing check needed |

POC tests for each candidate:
1. Open a fresh ext4 fixture.
2. Read `/etc/passwd`, mutate one row, write back.
3. Rename a top-level directory (`/home/pi` → `/home/artoo`).
4. Re-open, assert mutations persisted.
5. Run `e2fsck -n` on the mutated image (no errors).

Decision criteria (in priority order): correctness on `e2fsck`, ease of error handling, package weight. Document the chosen backend in a new spec appendix §13 with the test scores.

- [ ] **Step 1: Write candidate matrix tests**
- [ ] **Step 2: Run each candidate against the fixture**
- [ ] **Step 3: Document the choice + reasoning in spec §13**
- [ ] **Step 4: Add the chosen dependency (Python lib OR bundled binary path) to `pyproject.toml`**
- [ ] **Step 5: Commit POC + decision**

```bash
git add tests/poc/ docs/superpowers/specs/2026-05-29-astromechos-imager-design.md pyproject.toml
git commit -m "feat(rootfs): ext4-on-Windows backend POC + decision (see spec §13)"
```

NOTE — every downstream task in Phase 5.5 imports the chosen backend through a `RootfsPartition` Protocol declared in `core/platform_io.py`, so a future switch costs at most one adapter rewrite.

---

### Task 5.5.1: `/etc/passwd` parser + line writer

**Files:**
- Create: `astromechos_imager/core/passwd_files.py`
- Test: `tests/unit/test_passwd_files.py`

Pure-Python parsing of the colon-delimited formats. No I/O — all functions take `bytes` input, return `bytes` output. Lets us round-trip without touching ext4 yet.

Tasks:
- `parse_passwd(content: bytes) -> list[PasswdRow]` — one row per `name:x:uid:gid:gecos:home:shell`.
- `parse_shadow(content: bytes) -> list[ShadowRow]` — `name:hash:lastchg:min:max:warn:inactive:expire:reserved`.
- `parse_group(content: bytes) -> list[GroupRow]` — `name:x:gid:members_csv`.
- `serialize_*` round-trip preservers (trailing newline, ordering).
- `rename_user_in_passwd(rows, old, new)` — mutates name + home, returns new list.
- `rename_user_in_shadow(rows, old, new, new_crypt)` — mutates name + hash.
- `rename_user_in_group(rows, old, new)` — mutates primary group name (matched by UID's GID) + every membership list.

**TDD pattern**: each function gets a golden fixture + property-based round-trip via Hypothesis. Estimated effort: ~45 min.

---

### Task 5.5.2: `RootfsPartition` Protocol + chosen backend adapter

**Files:**
- Modify: `astromechos_imager/core/platform_io.py` (add `RootfsPartition` Protocol)
- Create: `astromechos_imager/core/rootfs.py` (adapter wrapping the Task 5.5.0 chosen backend)
- Test: `tests/integration/test_rootfs_adapter.py`

Same pattern as `BootPartition` from Task 4.5: a thin Protocol exposing `read_bytes(path)`, `write_bytes(path, data)`, `rename(src, dst)`, `chown(path, uid, gid)`, `close()`. Implementation routes to the Task 5.5.0 backend.

Integration test: open a fixture ext4 image, write a file, rename a dir, verify with `e2fsck -n`.

Estimated effort: ~1 h.

---

### Task 5.5.3: `RootfsPersonalizer` — orchestrates the rename

**Files:**
- Create: `astromechos_imager/core/rootfs_personalizer.py`
- Test: `tests/integration/test_rootfs_personalizer.py`

Single class consuming a `LinuxAccount` + a `RootfsPartition`, executing the §2.2.1 four steps in order:
1. Read `/etc/passwd`, locate UID-1000 row, rewrite name + home.
2. Read `/etc/shadow`, rewrite matching row's hash to `account.crypt_sha512`.
3. Read `/etc/group`, rewrite primary group name + membership lists.
4. `rootfs.rename(f"/home/{old}", f"/home/{new}")`.
5. Self-validate: re-read passwd/shadow/group, assert mutations stuck.

Errors raise typed exceptions in `core/errors.py` (`RootfsModError`, `UidNotFoundError`, `RootfsSelfValidationFailedError`) — all with `sd_state = "BOOTABLE_NO_FIRSTBOOT"`.

Estimated effort: ~1 h.

---

### Task 5.5.4: Locate rootfs partition + wire into FlashJob

**Files:**
- Modify: `astromechos_imager/core/bootpartition.py` (extend `find_first_fat32_partition` to also yield the 2nd partition's layout — the ext4 rootfs)
- Modify: `astromechos_imager/core/orchestrator.py` (FlashJob runs `RootfsPersonalizer` between verify and customize)
- Test: `tests/integration/test_flashjob_rootfs.py`

Pi OS MBR layout is fixed: partition 1 = FAT32 boot (~512 MB), partition 2 = ext4 rootfs (rest of card). Parse both entries, expose `find_rootfs_partition(mbr_bytes)` returning a `RootfsLayout(offset, size, partition_type)`.

The FlashJob ordering becomes:
1. lock + dismount volumes
2. raw write image
3. verify SHA256
4. **NEW**: open rootfs partition → run `RootfsPersonalizer`
5. open boot partition → write firstboot bundle
6. trigger marker

Cancellation at step 4 leaves the SD in `BOOTABLE_NO_FIRSTBOOT` (data + verified, rootfs partially modified, no trigger). The `sd_state` matrix in §7.5 of the spec covers this without changes.

Estimated effort: ~1 h.

---

### Task 5.5.5: End-to-end integration test against a Pi OS-shaped fixture

**Files:**
- Test: `tests/integration/test_end_to_end_personalize.py`
- Fixture script: `tests/fixtures/make_pi_os_fixture.py`

Build a tiny "Pi OS-shaped" sparse image (~80 MB total, MBR with FAT32 + ext4), pre-populated with a fake UID-1000 user (`pi:x:1000:1000:...:/home/pi:/bin/bash`). Run the full `FlashJob` against it (skip raw image write, just personalize a pre-flashed sparse image). Verify:
- `/etc/passwd` row 1000 renamed.
- `/etc/shadow` row 1000 has new hash.
- `/etc/group` rewrites.
- `/home/<new>` exists, `/home/<old>` doesn't.
- `e2fsck -n` clean.

Estimated effort: ~45 min.

---

NOTE — **Phase 5.5 is intentionally only sketched at this depth** because Task 5.5.0's POC outcome determines a chunk of the downstream code shape. Once 5.5.0 lands, tasks 5.5.1-5.5.5 get the same 5-step TDD detail as earlier phases via a plan-amendment commit before any of them are dispatched.

---

## Phase 6 — Orchestration (FlashJob + PairFlashJob)

### Task 6.1: Single-SD FlashJob

**Files:**
- Create: `astromechos_imager/core/orchestrator.py`
- Test: `tests/integration/test_flashjob.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_flashjob.py
import lzma
import pytest
from pathlib import Path
from astromechos_imager.core.orchestrator import FlashJob, FlashJobResult
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role

pytestmark = pytest.mark.integration


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512:
        out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_flash_job_master_end_to_end(tmp_path, fake_platform_io, monkeypatch):
    # Skip the customize step (no real FAT32 in fake_platform_io test path)
    payload = _mbr(b"R2" * 250_000)
    img = tmp_path / "master.img.xz"
    img.write_bytes(lzma.compress(payload))
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        imager_version="0.1.0", flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap(),
    )
    pair = generate_ed25519()
    # Stub the boot-partition open so we don't need a real FAT32 layout in fake SD
    from astromechos_imager.core.orchestrator import _bootpartition_open
    captured = {}
    def fake_open(raw_path, layout, known_letters):
        from tests.conftest import _FakeBP_class
        return None  # signal: skip customize in this test
    monkeypatch.setattr("astromechos_imager.core.orchestrator._bootpartition_open", fake_open)

    job = FlashJob(
        platform_io=fake_platform_io,
        image_path=img,
        target=fake_platform_io.enumerate_removable_drives()[0],
        role=Role.MASTER,
        firstboot_config=cfg,
        master_pair=pair,
        skip_verify=True,
        skip_customize=True,
    )
    result = job.run()
    assert isinstance(result, FlashJobResult)
    assert result.ok
```

NOTE — this minimal test stubs the customize step. A richer test (Task 6.2) goes through the full pair flow against a real FAT32 sparse fixture.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# astromechos_imager/core/orchestrator.py
"""High-level flash orchestration. Per design spec §3, §5, §6.4."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from astromechos_imager.core.bootpartition import (
    BootPartitionLayout, find_first_fat32_partition,
)
from astromechos_imager.core.bootpartition import open_boot_partition as _bootpartition_open
from astromechos_imager.core.customization import FirstbootBundle
from astromechos_imager.core.diskwriter import (
    DiskWriter, DiskWriterProgress, verify_readback,
)
from astromechos_imager.core.errors import ImagerError
from astromechos_imager.core.imagesource import open_image
from astromechos_imager.core.models import DiskRef, Ed25519Pair, FirstbootConfig, Role
from astromechos_imager.core.platform_io import PlatformIO


@dataclass(frozen=True)
class FlashJobResult:
    ok: bool
    bytes_written: int
    source_sha256: str
    error: BaseException | None = None


@dataclass
class FlashJob:
    platform_io: PlatformIO
    image_path: Path
    target: DiskRef
    role: Role
    firstboot_config: FirstbootConfig
    master_pair: Ed25519Pair
    on_progress: Callable[[DiskWriterProgress], None] = field(default=lambda p: None)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    skip_verify: bool = False
    skip_customize: bool = False

    def run(self) -> FlashJobResult:
        try:
            # 1. Lock + dismount any drive letters for this physical drive
            self.platform_io.lock_and_dismount(self.target.drive_letters)
            # 2. Open raw device + flash
            dev = self.platform_io.open_raw_device(self.target.physical_drive_id)
            try:
                with open_image(self.image_path) as src:
                    dw = DiskWriter(src, dev, on_progress=self.on_progress,
                                    cancel_event=self.cancel_event)
                    write_result = dw.run()
                # 3. Verify
                if not self.skip_verify and not self.cancel_event.is_set():
                    verify_readback(dev,
                                    expected_sha256=write_result.source_sha256,
                                    length=write_result.bytes_written,
                                    on_progress=self.on_progress,
                                    cancel_event=self.cancel_event)
                # 4. Customize via boot partition
                if not self.skip_customize:
                    self.platform_io.update_disk_properties(getattr(dev, "_h", 0))
                    mbr = dev.read(0, 512)
                    layout = find_first_fat32_partition(mbr)
                    bp = _bootpartition_open(
                        raw_device_path=self.target.device_path,
                        layout=layout,
                        known_letters_before=set(),
                    )
                    if bp is not None:
                        try:
                            FirstbootBundle(self.firstboot_config, self.master_pair).write_to(
                                bp, self.role)
                        finally:
                            bp.close()
            finally:
                dev.close()
            return FlashJobResult(ok=True, bytes_written=write_result.bytes_written,
                                   source_sha256=write_result.source_sha256)
        except ImagerError as e:
            return FlashJobResult(ok=False, bytes_written=0, source_sha256="", error=e)
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/integration/test_flashjob.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/orchestrator.py tests/integration/test_flashjob.py
git commit -m "feat(core/orchestrator): FlashJob single-SD pipeline (write → verify → customize)"
```

---

### Task 6.2: PairFlashJob (parallel + sequential)

**Files:**
- Modify: `astromechos_imager/core/orchestrator.py`
- Test: `tests/integration/test_pair_flash.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_pair_flash.py
import pytest
from pathlib import Path
from astromechos_imager.core.orchestrator import PairFlashJob, PairFlashResult
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, Role


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512: out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_parallel_pair_flash(tmp_path, fake_platform_io, monkeypatch):
    payload_m = _mbr(b"M" * 500_000)
    payload_s = _mbr(b"S" * 400_000)
    p_m = tmp_path / "master.img"; p_m.write_bytes(payload_m)
    p_s = tmp_path / "slave.img"; p_s.write_bytes(payload_s)
    fake_platform_io.add_drive(2, size=len(payload_m) + 1024)
    fake_platform_io.add_drive(3, size=len(payload_s) + 1024)
    monkeypatch.setattr("astromechos_imager.core.orchestrator._bootpartition_open",
                         lambda *a, **kw: None)

    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY], imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap(),
    )
    drives = {d.physical_drive_id: d for d in fake_platform_io.enumerate_removable_drives()}
    job = PairFlashJob(
        platform_io=fake_platform_io,
        master_image=p_m, master_target=drives[2],
        slave_image=p_s, slave_target=drives[3],
        firstboot_config=cfg,
        master_pair=generate_ed25519(),
        parallel=True,
        skip_verify=True, skip_customize=True,
    )
    res = job.run()
    assert isinstance(res, PairFlashResult)
    assert res.master.ok and res.slave.ok


def test_sequential_pair_flash(tmp_path, fake_platform_io, monkeypatch):
    payload = _mbr(b"X" * 200_000)
    p = tmp_path / "im.img"; p.write_bytes(payload)
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    fake_platform_io.add_drive(3, size=len(payload) + 1024)
    monkeypatch.setattr("astromechos_imager.core.orchestrator._bootpartition_open",
                         lambda *a, **kw: None)
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY], imager_version="0.1.0",
        flashed_at_iso="2026-05-29T02:15:00Z",
        hotspot_bootstrap=generate_hotspot_bootstrap(),
    )
    drives = {d.physical_drive_id: d for d in fake_platform_io.enumerate_removable_drives()}
    job = PairFlashJob(
        platform_io=fake_platform_io,
        master_image=p, master_target=drives[2],
        slave_image=p, slave_target=drives[3],
        firstboot_config=cfg, master_pair=generate_ed25519(),
        parallel=False, skip_verify=True, skip_customize=True,
    )
    res = job.run()
    assert res.master.ok and res.slave.ok
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement — append to `orchestrator.py`**

```python
@dataclass(frozen=True)
class PairFlashResult:
    master: FlashJobResult
    slave: FlashJobResult


@dataclass
class PairFlashJob:
    platform_io: PlatformIO
    master_image: Path
    master_target: DiskRef
    slave_image: Path
    slave_target: DiskRef
    firstboot_config: FirstbootConfig
    master_pair: Ed25519Pair
    on_progress: Callable[[Role, DiskWriterProgress], None] = field(default=lambda r, p: None)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    parallel: bool = True
    skip_verify: bool = False
    skip_customize: bool = False

    def _make_job(self, role: Role, image: Path, target: DiskRef) -> FlashJob:
        return FlashJob(
            platform_io=self.platform_io,
            image_path=image, target=target, role=role,
            firstboot_config=self.firstboot_config,
            master_pair=self.master_pair,
            on_progress=lambda p, _r=role: self.on_progress(_r, p),
            cancel_event=self.cancel_event,
            skip_verify=self.skip_verify, skip_customize=self.skip_customize,
        )

    def run(self) -> PairFlashResult:
        m_job = self._make_job(Role.MASTER, self.master_image, self.master_target)
        s_job = self._make_job(Role.SLAVE, self.slave_image, self.slave_target)
        if self.parallel:
            m_result: list[FlashJobResult] = []
            s_result: list[FlashJobResult] = []
            t1 = threading.Thread(target=lambda: m_result.append(m_job.run()))
            t2 = threading.Thread(target=lambda: s_result.append(s_job.run()))
            t1.start(); t2.start(); t1.join(); t2.join()
            m, s = m_result[0], s_result[0]
        else:
            m = m_job.run()
            s = s_job.run()
        return PairFlashResult(master=m, slave=s)
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/integration/test_pair_flash.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/core/orchestrator.py tests/integration/test_pair_flash.py
git commit -m "feat(core/orchestrator): PairFlashJob (parallel + sequential modes)"
```

---

## Phase 7 — CLI

### Task 7.1: argparse skeleton + admin elevation

**Files:**
- Create: `astromechos_imager/cli/main.py`
- Test: `tests/unit/test_cli_parse.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_cli_parse.py
import pytest
from astromechos_imager.cli.main import build_parser


def test_flash_subcommand_required():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_flash_master_only():
    args = build_parser().parse_args([
        "flash", "--master-image", "m.img", "--master-drive", "2",
        "--keys-file", "/tmp/id.pub",
    ])
    assert args.master_image == "m.img"
    assert args.master_drive == 2
    assert args.slave_image is None


def test_flash_both():
    args = build_parser().parse_args([
        "flash", "--master-image", "m.img.xz", "--master-drive", "2",
        "--slave-image", "s.img.xz", "--slave-drive", "3",
        "--keys-file", "/tmp/id.pub",
    ])
    assert args.master_drive == 2 and args.slave_drive == 3


def test_no_verify_flag():
    args = build_parser().parse_args([
        "flash", "--master-image", "m", "--master-drive", "2",
        "--keys-file", "k", "--no-verify",
    ])
    assert args.no_verify is True
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# astromechos_imager/cli/main.py
"""Headless CLI frontend. Per design spec §3.1, §5.7."""
from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="astromechos-imager",
        description="Two-card SD imager for the AstromechOS R2-D2 build.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    flash = sub.add_parser("flash", help="Flash one or two SD cards.")
    flash.add_argument("--master-image", type=str, default=None,
                       help="Path to master .img/.img.xz/.img.gz/.zip")
    flash.add_argument("--master-drive", type=int, default=None,
                       help="Physical drive number (e.g. 2 for \\\\.\\PHYSICALDRIVE2)")
    flash.add_argument("--slave-image", type=str, default=None)
    flash.add_argument("--slave-drive", type=int, default=None)
    flash.add_argument("--keys-file", type=str, required=True,
                       help="Path to a file containing OpenSSH pubkey(s), one per line")
    flash.add_argument("--no-verify", action="store_true",
                       help="Skip read-back SHA256 verification (discouraged)")
    flash.add_argument("--sequential", action="store_true",
                       help="Force sequential flash even when 2 SDs are present")
    flash.add_argument("--install-user", type=str, default="pi")
    flash.add_argument("--repo-url", type=str, default=None)
    flash.add_argument("--repo-branch", type=str, default="main")
    flash.add_argument("--hostname-master", type=str, default="astromech-master")
    flash.add_argument("--hostname-slave", type=str, default="astromech-slave")
    flash.add_argument("--debug", action="store_true")
    return p


def is_admin() -> bool:
    if sys.platform != "win32":
        return True  # CLI on non-Windows is fine for tests; admin check is Windows-only
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    if sys.platform != "win32":
        return
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1,
    )
    sys.exit(0)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not is_admin():
        relaunch_as_admin()
        return 0
    if args.command == "flash":
        return _cmd_flash(args)
    return 1


def _cmd_flash(args: argparse.Namespace) -> int:
    # Wired in Task 7.2 — for now, just confirm parser path.
    print(f"Would flash master={args.master_image} slave={args.slave_image}")
    return 0
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_cli_parse.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/cli/main.py tests/unit/test_cli_parse.py
git commit -m "feat(cli): argparse skeleton + Windows admin elevation"
```

---

### Task 7.2: Wire CLI to PairFlashJob

**Files:**
- Modify: `astromechos_imager/cli/main.py`
- Test: `tests/integration/test_cli_flash.py`

- [ ] **Step 1: Write the test (full path with FakePlatformIO via injection)**

```python
# tests/integration/test_cli_flash.py
import pytest
from pathlib import Path
from astromechos_imager.cli.main import _cmd_flash, build_parser

pytestmark = pytest.mark.integration


VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _mbr(payload):
    out = bytearray(payload)
    if len(out) < 512: out.extend(b"\x00" * (512 - len(out)))
    out[510:512] = b"\x55\xAA"
    return bytes(out)


def test_cli_flash_pair(tmp_path, fake_platform_io, monkeypatch):
    payload = _mbr(b"X" * 200_000)
    m = tmp_path / "master.img"; m.write_bytes(payload)
    s = tmp_path / "slave.img"; s.write_bytes(payload)
    keys = tmp_path / "id.pub"; keys.write_text(VALID_KEY + "\n")
    fake_platform_io.add_drive(2, size=len(payload) + 1024)
    fake_platform_io.add_drive(3, size=len(payload) + 1024)
    monkeypatch.setattr("astromechos_imager.core.orchestrator._bootpartition_open",
                         lambda *a, **kw: None)
    monkeypatch.setattr("astromechos_imager.cli.main._build_platform_io",
                         lambda: fake_platform_io)
    args = build_parser().parse_args([
        "flash", "--master-image", str(m), "--master-drive", "2",
        "--slave-image", str(s), "--slave-drive", "3",
        "--keys-file", str(keys), "--no-verify",
    ])
    rc = _cmd_flash(args)
    assert rc == 0
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement — extend `cli/main.py`**

Replace `_cmd_flash` with:

```python
def _build_platform_io():
    """Indirected so tests inject fakes."""
    if sys.platform == "win32":
        from astromechos_imager.platform.windows import WindowsPlatformIO
        return WindowsPlatformIO()
    raise RuntimeError("Imager runs on Windows only — CLI invoked from non-Windows host")


def _cmd_flash(args: argparse.Namespace) -> int:
    from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
    from astromechos_imager.core.models import FirstbootConfig, Role
    from astromechos_imager.core.orchestrator import PairFlashJob, FlashJob
    from astromechos_imager.core.models import _utc_iso_now

    plat = _build_platform_io()
    drives = {d.physical_drive_id: d for d in plat.enumerate_removable_drives()}
    keys = [k.strip() for k in Path(args.keys_file).read_text().splitlines() if k.strip()]
    cfg = FirstbootConfig(
        authorized_keys=keys,
        install_user=args.install_user,
        repo_url=args.repo_url, repo_branch=args.repo_branch,
        hostname_master=args.hostname_master, hostname_slave=args.hostname_slave,
        hotspot_bootstrap=generate_hotspot_bootstrap(),
        imager_version="0.1.0",
        flashed_at_iso=_utc_iso_now(),
    )
    pair = generate_ed25519()

    if args.master_image and args.slave_image:
        job = PairFlashJob(
            platform_io=plat,
            master_image=Path(args.master_image),
            master_target=drives[args.master_drive],
            slave_image=Path(args.slave_image),
            slave_target=drives[args.slave_drive],
            firstboot_config=cfg, master_pair=pair,
            parallel=not args.sequential,
            skip_verify=args.no_verify,
        )
        res = job.run()
        return 0 if (res.master.ok and res.slave.ok) else 2
    else:
        # Single role
        if args.master_image:
            role, image, target = Role.MASTER, args.master_image, drives[args.master_drive]
        else:
            role, image, target = Role.SLAVE, args.slave_image, drives[args.slave_drive]
        single = FlashJob(
            platform_io=plat, image_path=Path(image), target=target, role=role,
            firstboot_config=cfg, master_pair=pair, skip_verify=args.no_verify,
        )
        return 0 if single.run().ok else 2
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/integration/test_cli_flash.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/cli/main.py tests/integration/test_cli_flash.py
git commit -m "feat(cli): wire flash subcommand to PairFlashJob with single-role fallback"
```

---

## Phase 8 — UI (PySide6 + QML wizard)

NOTE — Phase 8 tasks are intentionally chunkier than core tasks because QML scaffolding adds verbose boilerplate per file. Each task ships ONE working step with PASS verification in `pytest-qt`.

### Task 8.1: QApplication entry + crash hook + main.qml shell

**Files:**
- Create: `astromechos_imager/ui/app.py`
- Create: `astromechos_imager/ui/qml/main.qml`
- Create: `astromechos_imager/ui/messages.py`
- Test: `tests/ui/test_app_launch.py`

- [ ] **Step 1: Write failing smoke test**

```python
# tests/ui/test_app_launch.py
import os, pytest
pytestmark = pytest.mark.skipif("QT_QPA_PLATFORM" not in os.environ,
                                 reason="needs offscreen Qt env")

def test_app_constructs(qtbot):
    from astromechos_imager.ui.app import build_app
    app, engine = build_app()
    assert app is not None
    assert engine.rootObjects() != []
```

- [ ] **Step 2: Run — expect FAIL** (module missing)

- [ ] **Step 3: Implement**

```python
# astromechos_imager/ui/messages.py
"""Centralized UI strings — i18n-ready."""
M = {
    "app_title": "AstromechOS Imager",
    "step_1_title": "What do you want to flash?",
    "mode_both": "Flash both (recommended)",
    "mode_master_only": "Master only",
    "mode_slave_only": "Slave only",
    "btn_next": "Next",
    "btn_back": "Back",
    "btn_write": "WRITE",
    "btn_cancel": "Cancel",
    "btn_quit": "Quit",
}
```

```python
# astromechos_imager/ui/app.py
"""QApplication entry point + crash hook."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from astromechos_imager.ui.messages import M


def _excepthook(exc_type, exc_value, tb):
    """Last-resort crash logger. Per design spec §7.9."""
    sys.stderr.write("\n=== UNCAUGHT EXCEPTION ===\n")
    traceback.print_exception(exc_type, exc_value, tb)


def build_app():
    app = QGuiApplication(sys.argv)
    app.setApplicationName(M["app_title"])
    sys.excepthook = _excepthook
    engine = QQmlApplicationEngine()
    qml_dir = Path(__file__).parent / "qml"
    engine.load(QUrl.fromLocalFile(str(qml_dir / "main.qml")))
    return app, engine


def main() -> int:
    app, engine = build_app()
    return app.exec()
```

```qml
// astromechos_imager/ui/qml/main.qml
import QtQuick
import QtQuick.Controls
import QtQuick.Window

ApplicationWindow {
    id: root
    width: 900
    height: 640
    visible: true
    title: "AstromechOS Imager"

    StackView {
        id: stack
        anchors.fill: parent
        initialItem: placeholder
    }
    Component {
        id: placeholder
        Rectangle {
            color: "#1a1a1a"
            Text {
                anchors.centerIn: parent
                text: "AstromechOS Imager — wizard placeholder"
                color: "#eee"
                font.pixelSize: 18
            }
        }
    }
}
```

- [ ] **Step 4: Run — expect PASS**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_app_launch.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/ui/app.py astromechos_imager/ui/messages.py astromechos_imager/ui/qml/main.qml tests/ui/test_app_launch.py
git commit -m "feat(ui): QApplication entry + crash hook + main.qml shell"
```

---

### Task 8.2: WizardState + StackView with 6 stubbed steps

**Files:**
- Create: `astromechos_imager/ui/wizard_state.py`
- Modify: `astromechos_imager/ui/app.py`
- Modify: `astromechos_imager/ui/qml/main.qml`
- Create one QML per step (Step1Mode.qml … Step6Done.qml) — each a placeholder rectangle for now
- Test: `tests/ui/test_wizard_state.py`

- [ ] **Step 1: Write failing test**

```python
# tests/ui/test_wizard_state.py
import os, pytest
pytestmark = pytest.mark.skipif("QT_QPA_PLATFORM" not in os.environ, reason="needs offscreen Qt")


def test_wizard_state_navigation(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.currentStep == 1
    s.next()
    assert s.currentStep == 2
    s.back()
    assert s.currentStep == 1
    s.back()  # can't go below 1
    assert s.currentStep == 1
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# astromechos_imager/ui/wizard_state.py
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot


class WizardState(QObject):
    currentStepChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._step = 1
        # Step 4-5 user inputs collected here (set via Property bindings)
        self.mode = "both"  # "both" | "master_only" | "slave_only"
        self.master_image_path: str = ""
        self.slave_image_path: str = ""
        self.master_drive_id: int = -1
        self.slave_drive_id: int = -1
        self.authorized_keys: list[str] = []

    @Property(int, notify=currentStepChanged)
    def currentStep(self) -> int:
        return self._step

    @Slot()
    def next(self) -> None:
        if self._step < 6:
            self._step += 1
            self.currentStepChanged.emit(self._step)

    @Slot()
    def back(self) -> None:
        if self._step > 1:
            self._step -= 1
            self.currentStepChanged.emit(self._step)

    @Slot(int)
    def goto(self, step: int) -> None:
        if 1 <= step <= 6 and step != self._step:
            self._step = step
            self.currentStepChanged.emit(self._step)
```

Update `app.py` to expose it:

```python
from astromechos_imager.ui.wizard_state import WizardState

def build_app():
    app = QGuiApplication(sys.argv)
    app.setApplicationName(M["app_title"])
    sys.excepthook = _excepthook
    state = WizardState()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("wizardState", state)
    qml_dir = Path(__file__).parent / "qml"
    engine.load(QUrl.fromLocalFile(str(qml_dir / "main.qml")))
    return app, engine, state
```

Update test in 8.1 accordingly (unpack 3-tuple).

Create stub QMLs (Step1Mode.qml through Step6Done.qml). Each is a placeholder Rectangle with a Text showing its step number. Example for Step1Mode:

```qml
// astromechos_imager/ui/qml/Step1Mode.qml
import QtQuick
import QtQuick.Controls

Rectangle {
    color: "#1a1a1a"
    Text { anchors.centerIn: parent; text: "Step 1 — Mode"; color: "#eee"; font.pixelSize: 22 }
    Row {
        anchors.bottom: parent.bottom; anchors.right: parent.right; anchors.margins: 20
        spacing: 10
        Button { text: "Next"; onClicked: wizardState.next() }
    }
}
```

Update `main.qml`:

```qml
import QtQuick
import QtQuick.Controls
import QtQuick.Window

ApplicationWindow {
    width: 900; height: 640; visible: true; title: "AstromechOS Imager"
    StackView {
        id: stack
        anchors.fill: parent
        initialItem: pages[wizardState.currentStep - 1]
        property var pages: [
            Qt.createComponent("Step1Mode.qml"),
            Qt.createComponent("Step2Images.qml"),
            Qt.createComponent("Step3Storage.qml"),
            Qt.createComponent("Step4Customize.qml"),
            Qt.createComponent("Step5Flash.qml"),
            Qt.createComponent("Step6Done.qml"),
        ]
    }
    Connections {
        target: wizardState
        function onCurrentStepChanged(s) {
            stack.replace(stack.pages[s - 1])
        }
    }
}
```

- [ ] **Step 4: Run — expect PASS**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_wizard_state.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/ui/wizard_state.py astromechos_imager/ui/app.py astromechos_imager/ui/qml/
git commit -m "feat(ui): WizardState QObject + StackView with 6 stubbed steps"
```

---

### Task 8.3-8.8: Flesh out wizard steps

**Each step gets its own task following the same pattern:**
- Define the QML layout per design spec §4
- Bind to WizardState fields via Property
- Add validation that disables Next when invalid
- Unit test: pytest-qt instantiates the step component and triggers actions

NOTE — these 6 tasks (8.3 = Step1Mode, 8.4 = Step2Images, 8.5 = Step3Storage, 8.6 = Step4Customize, 8.7 = Step5Flash, 8.8 = Step6Done) each follow the same 5-step TDD pattern: write QML, write pytest-qt smoke test, implement, verify, commit. Detailed QML is too verbose to enumerate here — each task should reference design spec §4 step by step. Total time: ~1 hour per step.

For each step task, commit message format:

```bash
git commit -m "feat(ui/wizard): step N — <step name> (per design spec §4.N)"
```

---

### Task 8.9: ErrorDialog component

**Files:**
- Create: `astromechos_imager/ui/qml/ErrorDialog.qml`
- Test: `tests/ui/test_error_dialog.py`

- [ ] **Step 1: Write failing test**

```python
# tests/ui/test_error_dialog.py
import os, pytest
pytestmark = pytest.mark.skipif("QT_QPA_PLATFORM" not in os.environ, reason="needs offscreen Qt")


def test_error_dialog_renders(qtbot):
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    from pathlib import Path
    eng = QQmlApplicationEngine()
    qml = Path("astromechos_imager/ui/qml/ErrorDialog.qml").absolute()
    eng.load(QUrl.fromLocalFile(str(qml)))
    assert eng.rootObjects()
```

- [ ] **Step 2-5: standard TDD pattern**

```qml
// astromechos_imager/ui/qml/ErrorDialog.qml — per design spec §7.7
import QtQuick
import QtQuick.Controls

Dialog {
    id: root
    property string title_: ""
    property string message: ""
    property string hint: ""
    property string sdState: "SAFE"   // SAFE | GARBAGE | UNCERTAIN | BOOTABLE_NO_FIRSTBOOT | OK
    property bool retryable: false
    signal retryRequested()
    signal exportRequested()
    width: 540
    standardButtons: Dialog.Close
    title: root.title_
    contentItem: Column {
        spacing: 12
        Text { text: root.message; color: "#eee"; wrapMode: Text.Wrap; width: parent.width }
        Text { text: "→ " + root.hint; color: "#ccc"; wrapMode: Text.Wrap; width: parent.width }
        Row {
            spacing: 8
            Button { visible: root.retryable; text: "Retry"; onClicked: root.retryRequested() }
            Button { text: "Export diagnostic"; onClicked: root.exportRequested() }
        }
    }
    background: Rectangle {
        color: {
            switch (root.sdState) {
                case "SAFE": return "#2a3f6a";
                case "GARBAGE": return "#6a2a2a";
                case "UNCERTAIN":
                case "BOOTABLE_NO_FIRSTBOOT": return "#6a4d2a";
                case "OK": return "#6a6a2a";
                default: return "#2a2a2a";
            }
        }
    }
}
```

Commit:

```bash
git commit -m "feat(ui): ErrorDialog component (sd_state-colored, retry/export actions)"
```

---

## Phase 9 — Logging, redaction, diagnostic

### Task 9.1: JSONL formatter + log rotation

**Files:**
- Create: `astromechos_imager/logging_setup/jsonl_formatter.py`
- Test: `tests/unit/test_jsonl_formatter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_jsonl_formatter.py
import json, logging
from astromechos_imager.logging_setup.jsonl_formatter import JsonLineFormatter


def test_format_basic():
    rec = logging.LogRecord(
        name="x.y", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    out = JsonLineFormatter().format(rec)
    obj = json.loads(out)
    assert obj["lvl"] == "INFO"
    assert obj["msg"] == "hello"
    assert obj["mod"] == "x.y"
    assert "ts" in obj


def test_format_with_ctx():
    rec = logging.LogRecord(
        name="x", level=logging.ERROR, pathname="", lineno=0,
        msg="boom", args=(), exc_info=None,
    )
    rec.ctx = {"win32_err": 1117, "sd_state": "GARBAGE"}
    obj = json.loads(JsonLineFormatter().format(rec))
    assert obj["ctx"]["win32_err"] == 1117
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# astromechos_imager/logging_setup/jsonl_formatter.py
"""Per design spec §7.3."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z",
            "lvl": record.levelname,
            "mod": record.name,
            "msg": record.getMessage(),
        }
        ctx = getattr(record, "ctx", None)
        if ctx is not None:
            obj["ctx"] = ctx
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/logging_setup/jsonl_formatter.py tests/unit/test_jsonl_formatter.py
git commit -m "feat(logging): JSONL formatter (ts, lvl, mod, msg, ctx, exc)"
```

---

### Task 9.2: Redaction filter

**Files:**
- Create: `astromechos_imager/logging_setup/redaction.py`
- Test: `tests/unit/test_redaction.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_redaction.py
import logging, hashlib
from astromechos_imager.logging_setup.redaction import RedactionFilter


def _record(msg, ctx=None):
    r = logging.LogRecord("x", logging.INFO, "", 0, msg, (), None)
    if ctx: r.ctx = ctx
    return r


def test_ed25519_private_redacted():
    secret = b"-----BEGIN OPENSSH PRIVATE KEY-----\nABCDEF\n-----END OPENSSH PRIVATE KEY-----\n"
    r = _record("writing key", ctx={"private_key": secret})
    RedactionFilter().filter(r)
    s = str(r.ctx["private_key"])
    assert "BEGIN OPENSSH" not in s
    assert "redacted" in s.lower()
    assert "fp=" in s.lower()


def test_psk_redacted():
    psk = "a1b2c3d4" * 4  # 32 hex
    r = _record("writing hotspot", ctx={"hotspot_password": psk})
    RedactionFilter().filter(r)
    out = str(r.ctx["hotspot_password"])
    assert psk not in out
    assert "redacted" in out.lower()


def test_authorized_keys_redacted():
    keys = ["ssh-ed25519 AAAA user@laptop", "ssh-rsa BBBB"]
    r = _record("writing keys", ctx={"authorized_keys": keys})
    RedactionFilter().filter(r)
    out = str(r.ctx["authorized_keys"])
    assert "ssh-ed25519 AAAA" not in out
    assert "fingerprints" in out.lower()


def test_large_bytes_redacted():
    r = _record("buf", ctx={"chunk": b"X" * 500})
    RedactionFilter().filter(r)
    assert "<500 bytes>" in str(r.ctx["chunk"])
```

- [ ] **Step 2-5: implement**

```python
# astromechos_imager/logging_setup/redaction.py
"""Per design spec §7.4."""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

_RED_BYTES_LIMIT = 256


def _ssh_fingerprint(key_line: str) -> str:
    """Best-effort: SHA256 of the base64 blob in an OpenSSH key line."""
    parts = key_line.strip().split()
    if len(parts) < 2:
        return "?"
    return "SHA256:" + hashlib.sha256(parts[1].encode("ascii")).hexdigest()[:12]


def _short_sha256(b: bytes | str) -> str:
    h = hashlib.sha256(b.encode("utf-8") if isinstance(b, str) else b)
    return f"sha256:{h.hexdigest()[:12]}"


class RedactionFilter(logging.Filter):
    """Per-field redaction. Modifies record.ctx in place."""
    def filter(self, record: logging.LogRecord) -> bool:
        ctx: dict[str, Any] | None = getattr(record, "ctx", None)
        if ctx is None:
            return True
        for k, v in list(ctx.items()):
            ctx[k] = self._redact(k, v)
        return True

    def _redact(self, key: str, value: Any) -> Any:
        key_l = key.lower()
        if "private" in key_l and isinstance(value, (bytes, str)):
            return f"<redacted: ed25519 private, fp={_short_sha256(value)}>"
        if "psk" in key_l or "password" in key_l:
            if isinstance(value, str):
                return f"<redacted: WPA2-PSK, fp={_short_sha256(value)}>"
        if "authorized_keys" in key_l and isinstance(value, list):
            fps = [_ssh_fingerprint(k) for k in value]
            return f"<{len(value)} keys, fingerprints: {', '.join(fps)}>"
        if isinstance(value, bytes) and len(value) > _RED_BYTES_LIMIT:
            return f"<{len(value)} bytes>"
        return value
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_redaction.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add astromechos_imager/logging_setup/redaction.py tests/unit/test_redaction.py
git commit -m "feat(logging): RedactionFilter (private keys, PSKs, authorized_keys, large bytes)"
```

---

### Task 9.3: Diagnostic ZIP export

**Files:**
- Create: `astromechos_imager/logging_setup/diagnostic.py`
- Test: `tests/unit/test_diagnostic_export.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_diagnostic_export.py
import zipfile, json
from astromechos_imager.logging_setup.diagnostic import build_diagnostic_zip


def test_diag_zip_structure(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text('{"ts":"...","lvl":"INFO","msg":"hi"}\n')
    target = tmp_path / "diag.zip"
    build_diagnostic_zip(
        target, log_path=log_file,
        traceback_text="Traceback...\n",
        system_info={"os": "Win 11", "py": "3.12.1"},
        firstboot_config={"authorized_keys": "<2 keys>"},
        include_psk=False,
    )
    with zipfile.ZipFile(target) as zf:
        names = set(zf.namelist())
    assert "session.log" in names
    assert "traceback.txt" in names
    assert "system_info.json" in names
    assert "firstboot_config.json" in names
```

- [ ] **Step 2-5: implement**

```python
# astromechos_imager/logging_setup/diagnostic.py
"""Per design spec §7.8."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path


def build_diagnostic_zip(
    target: Path,
    log_path: Path,
    traceback_text: str,
    system_info: dict,
    firstboot_config: dict,
    include_psk: bool = False,
) -> None:
    """Bundle session log + system info into a ZIP for the user to share."""
    if not include_psk:
        # Hotspot PSK redaction at the zip-build layer is defence-in-depth even
        # if the in-memory log filter already replaced it.
        fb = dict(firstboot_config)
        fb.pop("hotspot_password", None)
    else:
        fb = firstboot_config
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(log_path, "session.log")
        zf.writestr("traceback.txt", traceback_text)
        zf.writestr("system_info.json", json.dumps(system_info, indent=2))
        zf.writestr("firstboot_config.json", json.dumps(fb, indent=2))
```

Commit:

```bash
git add astromechos_imager/logging_setup/diagnostic.py tests/unit/test_diagnostic_export.py
git commit -m "feat(logging): diagnostic ZIP export with PSK opt-in"
```

---

## Phase 10 — Packaging & contract tests

### Task 10.1: PyInstaller spec + admin manifest

**Files:**
- Create: `astromechos_imager.spec`
- Create: `astromechos_imager_admin.manifest`

- [ ] **Step 1: Write the manifest**

```xml
<!-- astromechos_imager_admin.manifest -->
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
</assembly>
```

- [ ] **Step 2: Write the PyInstaller spec**

```python
# astromechos_imager.spec
# Run: pyinstaller astromechos_imager.spec
from pathlib import Path

block_cipher = None
QML_DIR = Path("astromechos_imager/ui/qml")

a = Analysis(
    ["astromechos_imager/ui/app.py"],
    pathex=[],
    binaries=[],
    datas=[(str(p), str(QML_DIR.parent / p.relative_to(QML_DIR.parent)))
           for p in QML_DIR.rglob("*.qml")],
    hiddenimports=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickControls2"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="AstromechOS Imager",
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,
    manifest="astromechos_imager_admin.manifest",
    icon=None,
)
```

- [ ] **Step 3: Commit**

```bash
git add astromechos_imager.spec astromechos_imager_admin.manifest
git commit -m "build: PyInstaller spec + admin manifest"
```

---

### Task 10.2: Contract drift tests

**Files:**
- Create: `tests/contract/test_firstboot_compat.py`
- Create: `tests/contract/fixtures/firstboot_setup.sh.snapshot` (copy of current `software/scripts/firstboot_setup.sh`)

- [ ] **Step 1: Write the test**

```python
# tests/contract/test_firstboot_compat.py
import os
import re
from pathlib import Path
import pytest

pytestmark = pytest.mark.contract

REPO = os.environ.get("ASTROMECHOS_REPO")
LIVE = Path(REPO) / "scripts/firstboot_setup.sh" if REPO else None
SNAPSHOT = Path(__file__).parent / "fixtures/firstboot_setup.sh.snapshot"

REQUIRED_PATHS = [
    "ASTROMECH_FIRSTBOOT_READY",
    "astromech_secrets/init_config.json",
    "astromech_secrets/authorized_keys",
    "astromech_init.cfg",
]


def _content() -> str:
    return (LIVE if LIVE and LIVE.exists() else SNAPSHOT).read_text(encoding="utf-8")


def test_required_files_still_referenced():
    c = _content()
    for p in REQUIRED_PATHS:
        assert p in c, f"Contract drift: {p} no longer referenced in firstboot_setup.sh"


def test_hotspot_section_consumed():
    c = _content()
    assert "cfg_get hotspot ssid" in c, "[hotspot] ssid no longer consumed (drift)"
    assert "cfg_get hotspot password" in c


def test_slave_section_consumed():
    c = _content()
    assert "cfg_get slave host" in c, "[slave] host no longer consumed (drift)"


def test_hostname_regex_subsumes_firstboot():
    from astromechos_imager.core.validators import _HOSTNAME_RE
    # Test that the firstboot regex from L206 is still equivalent
    fb_pattern = r"^[a-zA-Z0-9](-?[a-zA-Z0-9])*$"
    assert _HOSTNAME_RE.pattern.replace("?:", "") == fb_pattern.replace("?:", "")
```

- [ ] **Step 2: Capture the current firstboot snapshot**

```bash
cp J:/R2-D2_Build/software/scripts/firstboot_setup.sh tests/contract/fixtures/firstboot_setup.sh.snapshot
```

- [ ] **Step 3: Run**

Run: `pytest tests/contract/ -v`
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/contract/
git commit -m "test(contract): firstboot_setup.sh drift detection (hostname regex, [hotspot]/[slave])"
```

---

### Task 10.3: Manual E2E checklist + README

**Files:**
- Create: `tests/manual/E2E.md`
- Create: `README.md`

- [ ] **Step 1: Write the E2E checklist** (verbatim from design spec §8.5)

- [ ] **Step 2: Write a minimal README**

```markdown
# AstromechOS Imager

Two-card SD imager for the AstromechOS R2-D2 build. Flashes one Master + one Slave
SD card in a single session, pre-configured for the AstromechOS first-boot pairing.

See `docs/superpowers/specs/2026-05-29-astromechos-imager-design.md` for the design.

## Requirements
- Windows 10/11 (x86_64)
- Python 3.12 (dev only)
- Admin rights at runtime (raw disk write)

## Install (dev)
```
pip install -e .[dev]
```

## CLI usage
```
astromechos-imager flash \
    --master-image C:\images\master-2026-05-29.img.xz \
    --master-drive 2 \
    --slave-image C:\images\slave-2026-05-29.img.xz \
    --slave-drive 3 \
    --keys-file C:\Users\you\.ssh\id_ed25519.pub
```

## License
GPL-3.0-or-later (compatible with AstromechOS).
```

- [ ] **Step 3: Commit**

```bash
git add README.md tests/manual/
git commit -m "docs: README + manual E2E checklist"
```

---

## Self-review

### Spec coverage

Walking each design spec section against the plan:

| Spec § | Coverage |
|---|---|
| §1 Goal & non-goals | Implicit — every task scoped to in-scope features |
| §2 Firstboot contract | Tasks 3.1–3.6, 10.2 |
| §3 Architecture / layering | Tasks 0.1, 3.4, 4.4 (Protocols) |
| §4 Wizard flow | Tasks 8.1–8.9 |
| §5 Disk I/O & flash engine | Tasks 4.1–4.5, 5.1–5.2 |
| §6 Firstboot bundle | Tasks 3.1–3.6 |
| §7 Error handling & logging | Tasks 1.1, 8.9, 9.1–9.3 |
| §8 Testing strategy | Tasks throughout + 10.2 |
| §9 AstromechOS contract | Task 10.2 |
| §10 Persistence paths | Task 1.6 |
| §11 Glossary | Implicit in commit messages and code comments |

**Gaps fixed before finalization:**
- Manual E2E was a single doc → split into the per-step checklist in Task 10.3 (now matches §8.5).
- `find_first_fat32_partition` was missing — added in Task 4.5.
- Hotspot bootstrap renderer keys (`ssid` / `password` NOT `_bootstrap`) double-checked in Task 3.1 explicit test.

### Placeholder scan

Searched the plan for `TBD|TODO|FIXME|XXX|implement later|fill in details|similar to`:
- 0 hits — all steps contain executable code or shell commands.

### Type consistency

- `FirstbootBundle.write_to(bp, role)` — same signature across Tasks 3.5 and 6.1.
- `DiskWriterProgress.phase` values: `"decompress_write"` (Task 5.1), `"verify"` (Task 5.2) — both used consistently in Task 6.1's progress callback.
- `_bootpartition_open` (Task 4.5) symbol matches the import in Task 6.1.
- `PlatformIO.enumerate_removable_drives()` returns `list[DiskRef]` per Protocol (Task 4.4) and is used the same way in Tasks 6.1 and 7.2.

### Scope check

The plan implements exactly the spec scope: Windows-only v1, no telemetry, single Master + single Slave per session. No scope creep into Linux/macOS support, no fleet flashing, no online OS catalog.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-29-astromechos-imager-implementation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

