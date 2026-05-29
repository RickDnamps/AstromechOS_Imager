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
