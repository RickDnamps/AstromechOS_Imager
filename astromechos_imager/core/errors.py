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

class InvalidHostnameError(ConfigValidationError): ...
class InvalidAuthorizedKeysError(ConfigValidationError): ...
class InvalidInstallUserError(ConfigValidationError): ...
class InvalidRepoUrlError(ConfigValidationError): ...
class InvalidBranchNameError(ConfigValidationError): ...
class InvalidHotspotSsidError(ConfigValidationError): ...
class InvalidHotspotPskError(ConfigValidationError): ...
class InvalidWifiSsidError(ConfigValidationError): ...
class InvalidWifiPskError(ConfigValidationError): ...


# ── Image role marker validation: SD untouched, image refused ─────────────
# Hard-block family raised by core/image_validator.py when the selected
# image's /astromech_role.json on the boot FAT32 partition is missing,
# malformed, from a foreign project, or carries a role that does not match
# the user-selected slot. SD card is never touched on these — sd_state stays
# "SAFE" (inherited from PreflightError). The recovery_hint is in English
# (operator-facing) and ends up under the file picker / inside the
# ErrorDialog. See CLAUDE.md "Localization & language — STRICT RULE".

class ImageRoleValidationError(PreflightError):
    """Image's /astromech_role.json is missing, malformed, foreign, or mismatched."""


class MissingRoleMarkerError(ImageRoleValidationError):
    """No /astromech_role.json at the root of the boot FAT32 partition."""

    def __init__(self, image_name: str) -> None:
        super().__init__(
            f"image {image_name!r} has no /astromech_role.json on its boot partition"
        )
        self.recovery_hint = (
            "❌ FLASH BLOCKED: Non-certified AstromechOS image.\n\n"
            "The configuration file '/astromech_role.json' could not be found "
            "at the root of this image's boot partition. AstromechOS Imager "
            "refuses to flash an image whose origin cannot be verified.\n\n"
            "Likely cause: the image was not extracted from an AstromechOS SD "
            "card, or the role marker was removed after extraction.\n\n"
            "How to fix: re-extract the image from a working Pi (Master or "
            "Slave) that has the file '/boot/firmware/astromech_role.json' "
            "in place."
        )


class MalformedRoleMarkerError(ImageRoleValidationError):
    """/astromech_role.json exists but is invalid JSON, bad schema, or unknown role value."""

    def __init__(self, image_name: str, detail: str) -> None:
        super().__init__(
            f"/astromech_role.json on {image_name!r} is malformed: {detail}"
        )
        self.detail = detail
        self.recovery_hint = (
            "❌ FLASH BLOCKED: Invalid role marker.\n\n"
            "The file '/astromech_role.json' was found on the image's boot "
            "partition, but its contents do not match the expected format:\n\n"
            f"    {detail}\n\n"
            "Expected format:\n"
            "    {\"role\": \"master\" | \"slave\", \"project\": \"AstromechOS\", \"version\": \"2.0\"}\n\n"
            "How to fix: re-extract the image from a working Pi, or "
            "regenerate the marker following the documented procedure."
        )


class WrongProjectMarkerError(ImageRoleValidationError):
    """Marker valid JSON but project field != 'AstromechOS'."""

    def __init__(self, image_name: str, found_project: str) -> None:
        super().__init__(
            f"image {image_name!r} marker carries project={found_project!r}, expected 'AstromechOS'"
        )
        self.found_project = found_project
        self.recovery_hint = (
            "❌ FLASH BLOCKED: Image from another project.\n\n"
            f"This image carries a role marker for the project '{found_project}', "
            "but this tool only flashes **AstromechOS** images "
            "(the marker must have project=\"AstromechOS\").\n\n"
            "How to fix: pick a valid AstromechOS image, or use the flashing "
            "tool that ships with that other project."
        )


class RoleMismatchError(ImageRoleValidationError):
    """Marker valid but role doesn't match the user-selected slot."""

    def __init__(self, expected: str, found: str, image_name: str) -> None:
        super().__init__(
            f"image {image_name!r} carries role={found!r} but the selected slot expects {expected!r}"
        )
        self.expected = expected
        self.found = found
        self.recovery_hint = (
            "❌ FLASH BLOCKED: Wrong image for this slot.\n\n"
            f"You are about to flash this image into the **{expected.upper()}** "
            f"slot, but the image itself is tagged with role **{found.upper()}** "
            "(per '/astromech_role.json' on its boot partition).\n\n"
            "Flashing an image into the wrong Pi can brick the droid or "
            "create a silent master/slave conflict that only surfaces on the "
            "next boot.\n\n"
            "How to fix:\n"
            f"  - either pick an image whose role is '{expected}',\n"
            f"  - or change the target slot to '{found}'."
        )


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
