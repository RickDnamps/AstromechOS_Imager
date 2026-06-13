"""Unit tests for astromechos_imager.logging_setup.redaction."""
from __future__ import annotations

import logging

from hypothesis import given, settings
from hypothesis import strategies as st

from astromechos_imager.logging_setup.redaction import (
    RedactionFilter,
    _sha256_fingerprint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_with_ctx(ctx: dict) -> logging.LogRecord:  # type: ignore[type-arg]
    rec = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )
    rec.ctx = ctx  # type: ignore[attr-defined]
    return rec


def _apply_filter(ctx: dict) -> dict:  # type: ignore[type-arg]
    filt = RedactionFilter()
    rec = _record_with_ctx(ctx)
    filt.filter(rec)
    return rec.ctx  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# SHA-256 fingerprint
# ---------------------------------------------------------------------------


class TestSha256Fingerprint:
    def test_starts_with_sha256(self) -> None:
        fp = _sha256_fingerprint("secret")
        assert fp.startswith("sha256:")

    def test_12_hex_chars_after_prefix(self) -> None:
        fp = _sha256_fingerprint("secret")
        hex_part = fp[len("sha256:"):]
        assert len(hex_part) == 12
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_deterministic(self) -> None:
        assert _sha256_fingerprint("x") == _sha256_fingerprint("x")

    def test_different_values_different_fps(self) -> None:
        assert _sha256_fingerprint("a") != _sha256_fingerprint("b")


# ---------------------------------------------------------------------------
# Private key redaction
# ---------------------------------------------------------------------------


PRIVATE_KEY_PEM = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAA...\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


class TestPrivateKeyRedaction:
    def test_private_key_string_in_ctx_redacted(self) -> None:
        result = _apply_filter({"private_key": PRIVATE_KEY_PEM})
        assert "BEGIN OPENSSH" not in result["private_key"]
        assert "redacted" in result["private_key"]

    def test_key_named_private_redacted(self) -> None:
        """Any key containing 'private' is redacted even without PEM header."""
        result = _apply_filter({"my_private_stuff": "secret"})
        assert "redacted" in result["my_private_stuff"]
        assert "secret" not in result["my_private_stuff"]

    def test_fingerprint_included(self) -> None:
        result = _apply_filter({"private_key": PRIVATE_KEY_PEM})
        assert "sha256:" in result["private_key"]

    def test_private_key_bytes_redacted(self) -> None:
        key_bytes = PRIVATE_KEY_PEM.encode()
        result = _apply_filter({"private_key": key_bytes})
        val = result["private_key"]
        assert isinstance(val, str)
        assert "redacted" in val


# ---------------------------------------------------------------------------
# Password redaction
# ---------------------------------------------------------------------------


class TestPasswordRedaction:
    def test_cleartext_password_redacted(self) -> None:
        result = _apply_filter({"cleartext_password": "hunter2"})
        assert result["cleartext_password"] == "<redacted: password>"
        assert "hunter2" not in str(result)

    def test_linux_password_redacted(self) -> None:
        result = _apply_filter({"linux_password": "hunter2"})
        assert result["linux_password"] == "<redacted: password>"

    def test_key_containing_cleartext_password_redacted(self) -> None:
        result = _apply_filter({"user_cleartext_password_hash": "hunter2"})
        assert "hunter2" not in str(result)
        assert "redacted" in result["user_cleartext_password_hash"]

    def test_unrelated_key_not_redacted(self) -> None:
        result = _apply_filter({"hostname": "astromech-master"})
        assert result["hostname"] == "astromech-master"


# ---------------------------------------------------------------------------
# PSK / hotspot_password redaction
# ---------------------------------------------------------------------------


class TestPskRedaction:
    def test_psk_key_redacted(self) -> None:
        result = _apply_filter({"wpa2_psk": "MySecret123!"})
        assert "MySecret123!" not in str(result)
        assert "WPA2-PSK" in result["wpa2_psk"]
        assert "sha256:" in result["wpa2_psk"]

    def test_hotspot_password_key_redacted(self) -> None:
        result = _apply_filter({"hotspot_password": "BootstrapPass!"})
        assert "BootstrapPass!" not in str(result)
        assert "WPA2-PSK" in result["hotspot_password"]

    def test_psk_suffix_in_key_redacted(self) -> None:
        result = _apply_filter({"bootstrap_psk": "abc123"})
        assert "abc123" not in str(result)


# ---------------------------------------------------------------------------
# authorized_keys redaction
# ---------------------------------------------------------------------------


AUTHKEYS_LIST = [
    "ssh-ed25519 AAAA... user@host",
    "ssh-ed25519 BBBB... other@host",
]


class TestAuthorizedKeysRedaction:
    def test_list_replaced_with_fingerprint_summary(self) -> None:
        result = _apply_filter({"authorized_keys": AUTHKEYS_LIST})
        val = result["authorized_keys"]
        assert "2 keys" in val
        assert "AAAA" not in val
        assert "sha256:" in val

    def test_string_blob_replaced(self) -> None:
        blob = "\n".join(AUTHKEYS_LIST)
        result = _apply_filter({"authorized_keys": blob})
        val = result["authorized_keys"]
        assert "AAAA" not in val
        assert "sha256:" in val

    def test_empty_list_no_crash(self) -> None:
        result = _apply_filter({"authorized_keys": []})
        val = result["authorized_keys"]
        assert "0 keys" in val


# ---------------------------------------------------------------------------
# Bytes > 256 redaction
# ---------------------------------------------------------------------------


class TestBytesRedaction:
    def test_large_bytes_replaced(self) -> None:
        big = b"\x00" * 300
        result = _apply_filter({"raw_data": big})
        assert result["raw_data"] == "<300 bytes>"

    def test_small_bytes_not_replaced(self) -> None:
        small = b"\x00" * 10
        result = _apply_filter({"raw_data": small})
        # small bytes are not altered (no private/psk key match)
        assert result["raw_data"] == small

    def test_exactly_256_bytes_not_replaced(self) -> None:
        boundary = b"x" * 256
        result = _apply_filter({"raw_data": boundary})
        assert result["raw_data"] == boundary

    def test_257_bytes_replaced(self) -> None:
        result = _apply_filter({"raw_data": b"x" * 257})
        assert result["raw_data"] == "<257 bytes>"


# ---------------------------------------------------------------------------
# Path redaction
# ---------------------------------------------------------------------------


class TestPathRedaction:
    def test_windows_user_path_truncated_to_basename(self) -> None:
        path_str = r"C:\Users\RickDnamps\Documents\master.img.xz"
        result = _apply_filter({"image_path": path_str})
        val = result["image_path"]
        assert "RickDnamps" not in val
        assert val == "master.img.xz"

    def test_non_user_path_not_altered(self) -> None:
        path_str = r"D:\images\master.img"
        result = _apply_filter({"image_path": path_str})
        assert result["image_path"] == path_str


# ---------------------------------------------------------------------------
# RedactionFilter — filter() always returns True
# ---------------------------------------------------------------------------


class TestRedactionFilterPassThrough:
    def test_filter_always_returns_true(self) -> None:
        filt = RedactionFilter()
        rec = _record_with_ctx({"cleartext_password": "secret"})
        assert filt.filter(rec) is True

    def test_filter_no_ctx_attribute(self) -> None:
        filt = RedactionFilter()
        rec = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
        # Must not raise, must return True
        assert filt.filter(rec) is True

    def test_filter_ctx_none(self) -> None:
        filt = RedactionFilter()
        rec = _record_with_ctx({})
        rec.ctx = None  # type: ignore[attr-defined]
        assert filt.filter(rec) is True


# ---------------------------------------------------------------------------
# Hypothesis: private_key context never leaks secret material
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Free-text message scrub
#
# The ``record.msg`` scrub must prevent SSID/PSK/password literals from
# leaking into log lines (e.g. a session-start message carrying the raw
# hotspot SSID, or the JSONL session log capturing it).
# ---------------------------------------------------------------------------


class TestFreeTextLeakScrub:
    @staticmethod
    def _filtered_msg(msg: str, args: tuple = ()) -> str:
        rec = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=msg,
            args=args,
            exc_info=None,
        )
        RedactionFilter().filter(rec)
        return rec.getMessage()

    def test_ssid_pattern_redacted_in_msg(self) -> None:
        """``SSID=Astromech-1234`` in a log message becomes
        ``SSID=<redacted>``."""
        msg = "Sequential session started — hotspot SSID=Astromech-1234 (persists)"
        out = self._filtered_msg(msg)
        assert "Astromech-1234" not in out
        assert "SSID=<redacted>" in out

    def test_astromech_literal_redacted(self) -> None:
        """A bare ``Astromech-NNNN`` literal anywhere in the message
        becomes ``<redacted-SSID>`` (catch-all for callers who don't
        use the SSID= key=value form)."""
        out = self._filtered_msg("camped on Astromech-9876 rendezvous")
        assert "Astromech-9876" not in out
        assert "<redacted-SSID>" in out

    def test_psk_redacted(self) -> None:
        """``psk=...`` key=value pair is redacted (case-insensitive)."""
        out = self._filtered_msg("hotspot psk=Secr3tP@ss applied")
        assert "Secr3tP@ss" not in out
        assert "psk=<redacted>" in out

    def test_password_kv_redacted(self) -> None:
        """``password=...`` key=value pair is redacted."""
        out = self._filtered_msg("login password=hunter2 ok")
        assert "hunter2" not in out
        assert "password=<redacted>" in out

    def test_ssid_pattern_in_args_resolved_and_scrubbed(self) -> None:
        """The real FlashViewModel call uses ``%s`` formatting — the
        scrub must resolve ``record.args`` first then redact, so the
        SSID never reaches the JSONL formatter."""
        out = self._filtered_msg(
            "Sequential session started — hotspot SSID=%s (persists)",
            ("Astromech-4242",),
        )
        assert "Astromech-4242" not in out
        # Both patterns happen to match — either flavour of redaction
        # is acceptable as long as the raw SSID is gone.
        assert ("SSID=<redacted>" in out) or ("<redacted-SSID>" in out)

    def test_existing_ctx_redaction_still_works(self) -> None:
        """Regression guard: the ctx scrub keeps working alongside the
        new msg scrub. A record with BOTH a sensitive ctx key AND a
        sensitive msg must have both scrubbed."""
        rec = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hotspot SSID=Astromech-0001 active",
            args=(),
            exc_info=None,
        )
        rec.ctx = {"cleartext_password": "hunter2"}  # type: ignore[attr-defined]
        RedactionFilter().filter(rec)
        assert rec.ctx["cleartext_password"] == "<redacted: password>"  # type: ignore[attr-defined]
        assert "Astromech-0001" not in rec.getMessage()

    def test_unrelated_msg_unchanged(self) -> None:
        """Messages without any leak pattern pass through untouched —
        the scrub must not corrupt benign log lines."""
        msg = "Wrote 4 MiB to /dev/sdb at 23.4 MB/s"
        assert self._filtered_msg(msg) == msg


@given(st.text(min_size=1, max_size=500))
@settings(max_examples=200)
def test_private_key_never_leaks(secret: str) -> None:
    """For any string injected as 'private_key', the output must always be
    the standard redaction placeholder — never the raw secret.

    The redaction rule: any ``ctx`` key containing ``'private'`` is replaced
    with ``'<redacted: ed25519 private, fp=sha256:XXXXXXXXXXXX>'``.  The
    placeholder is a fixed-shape string; we verify it matches the expected
    pattern and that the raw secret does not appear *outside* the placeholder
    structure (i.e. the secret is not concatenated / interpolated raw).
    """
    import re

    result = _apply_filter({"private_key": secret})
    redacted = result["private_key"]

    # Must always be a well-formed redaction placeholder
    assert "redacted" in redacted, f"private_key not redacted for input: {secret!r}"
    # Must match the exact shape: <redacted: ed25519 private, fp=sha256:HHHHHHHHHHHH>
    assert re.fullmatch(
        r"<redacted: ed25519 private, fp=sha256:[0-9a-f]{12}>", redacted
    ), f"Unexpected redacted format: {redacted!r}"
