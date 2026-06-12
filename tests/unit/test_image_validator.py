"""Unit tests for image_validator.py — HARD BLOCK semantics.

Tests use the ``fake_boot_partition`` fixture from ``tests/conftest.py``
(in-memory BootPartition mock) to drive the schema/role logic without
needing a real .img file. The compression-resolution context manager and
real FAT32 path are exercised separately by integration tests.
"""
from __future__ import annotations

import json

import pytest

from astromechos_imager.core.errors import (
    ImageRoleValidationError,
    MalformedRoleMarkerError,
    MissingRoleMarkerError,
    RoleMismatchError,
    WrongProjectMarkerError,
)
from astromechos_imager.core.image_validator import (
    ROLE_MARKER_PATH,
    _validate_marker_from_bp,
    guess_role_from_filename,
)
from astromechos_imager.core.models import Role

# ── Filename heuristic (info-only helper) ────────────────────────────────

class TestGuessRoleFromFilename:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("astromech_master_2026_05_29.img", Role.MASTER),
            ("Pi-master-backup.img.xz", Role.MASTER),
            ("dome.img", Role.MASTER),
            ("astromech-head.img.gz", Role.MASTER),
            ("astromech_slave_2026_05_29.img", Role.SLAVE),
            ("pi-slave-snap.img.xz", Role.SLAVE),
            ("body.img", Role.SLAVE),
            ("base_extract.img.gz", Role.SLAVE),
        ],
    )
    def test_unambiguous_filenames_return_role(self, name, expected):
        assert guess_role_from_filename(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "raspios-bookworm.img.xz",     # no keyword
            "backup-2026-05-29.img",        # no keyword
            "image.img",                    # no keyword
            "master_slave_combo.img",       # both keywords → ambiguous
            "dome-body.img",                # both keywords → ambiguous
        ],
    )
    def test_ambiguous_or_unknown_returns_none(self, name):
        assert guess_role_from_filename(name) is None

    def test_case_insensitive(self):
        assert guess_role_from_filename("ASTROMECH_MASTER.IMG") == Role.MASTER
        assert guess_role_from_filename("AstroMech_Slave.Img") == Role.SLAVE

    def test_full_path_works(self):
        assert (
            guess_role_from_filename("/some/dir/astromech_master.img")
            == Role.MASTER
        )


# ── Marker validation: happy paths ───────────────────────────────────────

VALID_MASTER_MARKER = {
    "role": "master",
    "project": "AstromechOS",
    "version": "2.0",
}

VALID_SLAVE_MARKER = {
    "role": "slave",
    "project": "AstromechOS",
    "version": "2.0",
}


def _seed(bp, marker):
    """Write the given marker dict into the fake boot partition."""
    bp.write_bytes(ROLE_MARKER_PATH, json.dumps(marker).encode("utf-8"))


class TestValidatorHappyPath:
    def test_master_marker_master_slot_returns_marker(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, VALID_MASTER_MARKER)
        result = _validate_marker_from_bp(bp, "test.img", Role.MASTER)
        assert result == VALID_MASTER_MARKER

    def test_slave_marker_slave_slot_returns_marker(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, VALID_SLAVE_MARKER)
        result = _validate_marker_from_bp(bp, "test.img", Role.SLAVE)
        assert result == VALID_SLAVE_MARKER

    def test_extra_keys_in_marker_are_tolerated(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {**VALID_MASTER_MARKER, "extracted_from": "Pi-A", "notes": "ok"})
        result = _validate_marker_from_bp(bp, "test.img", Role.MASTER)
        assert result["role"] == "master"
        assert result["extracted_from"] == "Pi-A"

    def test_role_value_whitespace_and_case_normalised(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {**VALID_MASTER_MARKER, "role": "  MASTER  "})
        result = _validate_marker_from_bp(bp, "test.img", Role.MASTER)
        assert result["role"] == "  MASTER  "  # raw preserved in return


# ── Hard block: missing marker ───────────────────────────────────────────

class TestMissingMarker:
    def test_no_file_raises_missing_role_marker_error(self, fake_boot_partition):
        # Nothing written → marker absent
        with pytest.raises(MissingRoleMarkerError) as excinfo:
            _validate_marker_from_bp(fake_boot_partition, "raspios.img", Role.MASTER)
        assert "raspios.img" in str(excinfo.value)

    def test_missing_marker_recovery_hint_is_pedagogical_english(self, fake_boot_partition):
        with pytest.raises(MissingRoleMarkerError) as excinfo:
            _validate_marker_from_bp(fake_boot_partition, "raspios.img", Role.MASTER)
        hint = excinfo.value.recovery_hint
        assert "❌ FLASH BLOCKED" in hint
        assert "Non-certified" in hint
        assert "/astromech_role.json" in hint
        assert "How to fix" in hint

    def test_missing_marker_is_a_subclass_of_image_role_validation_error(
        self, fake_boot_partition
    ):
        with pytest.raises(ImageRoleValidationError):
            _validate_marker_from_bp(fake_boot_partition, "test.img", Role.MASTER)


# ── Hard block: malformed marker ─────────────────────────────────────────

class TestMalformedMarker:
    def test_not_json_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        bp.write_bytes(ROLE_MARKER_PATH, b"this is not json")
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert "invalid JSON" in excinfo.value.detail

    def test_not_utf8_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        bp.write_bytes(ROLE_MARKER_PATH, b"\xff\xfe\x00")  # invalid utf-8
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert "not valid UTF-8" in excinfo.value.detail

    def test_top_level_array_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        bp.write_bytes(ROLE_MARKER_PATH, b'["master", "AstromechOS", "2.0"]')
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert "JSON object" in excinfo.value.detail
        assert "list" in excinfo.value.detail

    def test_top_level_string_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        bp.write_bytes(ROLE_MARKER_PATH, b'"master"')
        with pytest.raises(MalformedRoleMarkerError):
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)

    def test_missing_role_key_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {"project": "AstromechOS", "version": "2.0"})
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert "role" in excinfo.value.detail

    def test_missing_project_key_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {"role": "master", "version": "2.0"})
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert "project" in excinfo.value.detail

    def test_missing_version_key_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {"role": "master", "project": "AstromechOS"})
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert "version" in excinfo.value.detail

    def test_role_non_string_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {"role": 42, "project": "AstromechOS", "version": "2.0"})
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert "role must be a string" in excinfo.value.detail

    def test_role_unknown_value_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {"role": "supervisor", "project": "AstromechOS", "version": "2.0"})
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert "master" in excinfo.value.detail
        assert "slave" in excinfo.value.detail

    def test_malformed_recovery_hint_includes_detail(self, fake_boot_partition):
        bp = fake_boot_partition
        bp.write_bytes(ROLE_MARKER_PATH, b"garbage{{")
        with pytest.raises(MalformedRoleMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        hint = excinfo.value.recovery_hint
        assert "❌ FLASH BLOCKED" in hint
        assert "Invalid role marker" in hint
        assert "re-extract" in hint


# ── Hard block: wrong project ────────────────────────────────────────────

class TestWrongProject:
    def test_unknown_project_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {"role": "master", "project": "SomeOtherDroid", "version": "1.0"})
        with pytest.raises(WrongProjectMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert excinfo.value.found_project == "SomeOtherDroid"

    def test_wrong_project_recovery_hint_in_english(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, {"role": "master", "project": "ChopperOS", "version": "1.0"})
        with pytest.raises(WrongProjectMarkerError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        hint = excinfo.value.recovery_hint
        assert "❌ FLASH BLOCKED" in hint
        assert "Image from another project" in hint
        assert "ChopperOS" in hint
        assert "AstromechOS" in hint


# ── Hard block: role mismatch ────────────────────────────────────────────

class TestRoleMismatch:
    def test_master_marker_slave_slot_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, VALID_MASTER_MARKER)
        with pytest.raises(RoleMismatchError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.SLAVE)
        assert excinfo.value.expected == "slave"
        assert excinfo.value.found == "master"

    def test_slave_marker_master_slot_raises(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, VALID_SLAVE_MARKER)
        with pytest.raises(RoleMismatchError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        assert excinfo.value.expected == "master"
        assert excinfo.value.found == "slave"

    def test_role_mismatch_recovery_hint_names_both_slots(self, fake_boot_partition):
        bp = fake_boot_partition
        _seed(bp, VALID_MASTER_MARKER)
        with pytest.raises(RoleMismatchError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.SLAVE)
        hint = excinfo.value.recovery_hint
        assert "❌ FLASH BLOCKED" in hint
        assert "Wrong image" in hint
        assert "SLAVE" in hint  # expected slot
        assert "MASTER" in hint  # found role
        assert "brick" in hint  # pedagogical: explains consequence

    def test_role_mismatch_recovery_hint_offers_two_corrective_actions(
        self, fake_boot_partition
    ):
        bp = fake_boot_partition
        _seed(bp, VALID_SLAVE_MARKER)
        with pytest.raises(RoleMismatchError) as excinfo:
            _validate_marker_from_bp(bp, "img.img", Role.MASTER)
        hint = excinfo.value.recovery_hint
        # Each bullet "either" appears for the two recovery paths.
        assert hint.lower().count("either") >= 1
        assert hint.lower().count("\n  - ") >= 2


# ── Cross-class invariant: every block is an ImageRoleValidationError ───

class TestExceptionHierarchy:
    @pytest.mark.parametrize(
        "exc_class",
        [
            MissingRoleMarkerError,
            MalformedRoleMarkerError,
            WrongProjectMarkerError,
            RoleMismatchError,
        ],
    )
    def test_all_block_exceptions_inherit_image_role_validation_error(self, exc_class):
        assert issubclass(exc_class, ImageRoleValidationError)

    def test_all_block_exceptions_are_safe_sd_state(self):
        """sd_state == 'SAFE' is the invariant: SD is NEVER touched on a
        role-validation failure, so the SD remains pristine for retry."""
        from astromechos_imager.core.errors import PreflightError
        assert issubclass(ImageRoleValidationError, PreflightError)
