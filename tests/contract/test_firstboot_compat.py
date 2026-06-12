"""Contract drift detection tests for AstromechOS firstboot_setup.sh.

These tests lock in the contract surface the Imager was built against.
They read from the committed ``fixtures/firstboot_setup.sh.snapshot`` by
default so that CI always validates against a known-good revision.

If the environment variable ``ASTROMECHOS_REPO`` is set to the path of a
live AstromechOS clone, the tests automatically validate against the live
``scripts/firstboot_setup.sh`` instead — useful during development.

How to regenerate the snapshot after an intentional contract change::

    cp $ASTROMECHOS_REPO/scripts/firstboot_setup.sh \\
        tests/contract/fixtures/firstboot_setup.sh.snapshot

Then re-run the tests to confirm they pass with the new snapshot.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

# ---------------------------------------------------------------------------
# Script source resolution
# ---------------------------------------------------------------------------

REPO = os.environ.get("ASTROMECHOS_REPO")
LIVE = Path(REPO) / "scripts/firstboot_setup.sh" if REPO else None
SNAPSHOT = Path(__file__).parent / "fixtures/firstboot_setup.sh.snapshot"

# Paths that must still be referenced in the script
REQUIRED_PATHS = [
    "ASTROMECH_FIRSTBOOT_READY",
    "astromech_secrets/init_config.json",
    "astromech_secrets/authorized_keys",
    "astromech_init.cfg",
]


def _content() -> str:
    """Return the text of the script to test against.

    Uses the live script when ASTROMECHOS_REPO is set and the file exists;
    otherwise falls back to the committed snapshot.
    """
    source = LIVE if LIVE and LIVE.exists() else SNAPSHOT
    return source.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_required_files_still_referenced() -> None:
    """All contract file paths must still appear in the script."""
    c = _content()
    for p in REQUIRED_PATHS:
        assert p in c, f"Contract drift: '{p}' no longer referenced in firstboot_setup.sh"


def test_hotspot_keys_consumed() -> None:
    """The [hotspot] section keys ssid and password must still be consumed."""
    c = _content()
    assert "cfg_get hotspot ssid" in c, (
        "Contract drift: 'cfg_get hotspot ssid' no longer in firstboot_setup.sh"
    )
    assert "cfg_get hotspot password" in c, (
        "Contract drift: 'cfg_get hotspot password' no longer in firstboot_setup.sh"
    )


def test_slave_keys_consumed() -> None:
    """The [slave] section keys host and user must still be consumed."""
    c = _content()
    assert "cfg_get slave host" in c, (
        "Contract drift: 'cfg_get slave host' no longer in firstboot_setup.sh"
    )
    assert "cfg_get slave user" in c, (
        "Contract drift: 'cfg_get slave user' no longer in firstboot_setup.sh"
    )


def test_admin_password_consumed() -> None:
    """The [admin] password key must still be consumed (Phase 5.5 contract)."""
    c = _content()
    assert "cfg_get admin password" in c, (
        "Contract drift: 'cfg_get admin password' no longer in firstboot_setup.sh"
    )


def test_hostname_regex_unchanged() -> None:
    """The hostname validation regex from L206 must be unchanged.

    The Imager's hostname validator (validators.py) was built to match the
    exact regex used in firstboot_setup.sh.  If this assertion fails it means
    the Pi-side validation changed and the Imager's ``validate_hostname()``
    must be updated to stay in sync.
    """
    c = _content()
    # Match the exact firstboot_setup.sh:206 regex fragment
    assert r"[a-zA-Z0-9](-?[a-zA-Z0-9])*" in c, (
        "Contract drift: hostname regex no longer matches "
        r"'[a-zA-Z0-9](-?[a-zA-Z0-9])*' in firstboot_setup.sh"
    )
