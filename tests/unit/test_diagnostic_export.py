"""Unit tests for astromechos_imager.logging_setup.diagnostic."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from astromechos_imager.logging_setup.diagnostic import (
    build_diagnostic_zip,
    collect_system_info,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_FIRSTBOOT_CFG = {
    "role": "master",
    "hostname": "astromech-master",
    "hotspot_password": "SensitivePSK123!",
    "cleartext_password": "hunter2",
    "linux_password": "hunter2",
    "ssid": "AstromechBootstrap",
}

SAMPLE_SYSTEM_INFO = {
    "os": "Windows",
    "arch": "AMD64",
    "python": "3.12.0",
    "app_version": "0.1.0",
}

TRACEBACK = "Traceback (most recent call last):\n  ...\nRuntimeError: boom"


def _build_zip(
    tmp_path: Path,
    log_contents: str | None = "log line 1\n",
    traceback_text: str = TRACEBACK,
    firstboot_config: dict | None = None,  # type: ignore[type-arg]
    include_psk: bool = False,
) -> zipfile.ZipFile:
    """Helper: build the ZIP, return an open ZipFile for inspection."""
    if firstboot_config is None:
        firstboot_config = dict(SAMPLE_FIRSTBOOT_CFG)

    log_path = tmp_path / "session.log"
    if log_contents is not None:
        log_path.write_text(log_contents, encoding="utf-8")

    zip_path = tmp_path / "diag.zip"
    build_diagnostic_zip(
        target=zip_path,
        log_path=log_path,
        traceback_text=traceback_text,
        system_info=SAMPLE_SYSTEM_INFO,
        firstboot_config=firstboot_config,
        include_psk=include_psk,
    )
    return zipfile.ZipFile(zip_path, "r")


# ---------------------------------------------------------------------------
# ZIP structure
# ---------------------------------------------------------------------------


class TestZipStructure:
    def test_zip_contains_required_files(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path)
        names = zf.namelist()
        assert "session.log" in names
        assert "traceback.txt" in names
        assert "system_info.json" in names
        assert "firstboot_config.json" in names

    def test_session_log_content_included(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path, log_contents="hello log\n")
        content = zf.read("session.log").decode()
        assert "hello log" in content

    def test_traceback_content_included(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path, traceback_text="Traceback: boom")
        content = zf.read("traceback.txt").decode()
        assert "Traceback: boom" in content

    def test_empty_traceback_writes_placeholder(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path, traceback_text="")
        content = zf.read("traceback.txt").decode()
        assert "no traceback" in content

    def test_missing_log_writes_placeholder(self, tmp_path: Path) -> None:
        """If session.log doesn't exist, a note is written instead."""
        zf = _build_zip(tmp_path, log_contents=None)
        content = zf.read("session.log").decode()
        assert "not found" in content

    def test_system_info_is_valid_json(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path)
        obj = json.loads(zf.read("system_info.json"))
        assert isinstance(obj, dict)

    def test_firstboot_config_is_valid_json(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path)
        obj = json.loads(zf.read("firstboot_config.json"))
        assert isinstance(obj, dict)


# ---------------------------------------------------------------------------
# Secrets stripped by default
# ---------------------------------------------------------------------------


class TestSecretsStrippedByDefault:
    def test_hotspot_password_stripped_by_default(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path, include_psk=False)
        cfg = json.loads(zf.read("firstboot_config.json"))
        assert "hotspot_password" not in cfg
        assert "SensitivePSK123!" not in json.dumps(cfg)

    def test_cleartext_password_always_stripped(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path, include_psk=False)
        cfg = json.loads(zf.read("firstboot_config.json"))
        assert "cleartext_password" not in cfg

    def test_linux_password_always_stripped(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path, include_psk=False)
        cfg = json.loads(zf.read("firstboot_config.json"))
        assert "linux_password" not in cfg

    def test_non_sensitive_fields_retained(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path, include_psk=False)
        cfg = json.loads(zf.read("firstboot_config.json"))
        assert cfg["role"] == "master"
        assert cfg["hostname"] == "astromech-master"
        assert cfg["ssid"] == "AstromechBootstrap"


# ---------------------------------------------------------------------------
# PSK opt-in
# ---------------------------------------------------------------------------


class TestPskOptIn:
    def test_hotspot_password_included_when_opted_in(self, tmp_path: Path) -> None:
        zf = _build_zip(tmp_path, include_psk=True)
        cfg = json.loads(zf.read("firstboot_config.json"))
        assert cfg.get("hotspot_password") == "SensitivePSK123!"

    def test_cleartext_password_still_stripped_even_with_psk_optin(
        self, tmp_path: Path
    ) -> None:
        """include_psk only unlocks PSK; linux password must never appear."""
        zf = _build_zip(tmp_path, include_psk=True)
        cfg = json.loads(zf.read("firstboot_config.json"))
        assert "cleartext_password" not in cfg
        assert "linux_password" not in cfg


# ---------------------------------------------------------------------------
# Nested config dict redaction
# ---------------------------------------------------------------------------


class TestNestedConfigRedaction:
    def test_nested_password_stripped(self, tmp_path: Path) -> None:
        """Nested dicts are recursed — hotspot_password inside a 'hotspot'
        sub-dict must also be stripped."""
        cfg = {
            "role": "master",
            "hotspot": {
                "ssid": "Bootstrap_1234",
                "password": "NestedSecret!",  # should be stripped
            },
        }
        log_path = tmp_path / "session.log"
        log_path.write_text("", encoding="utf-8")
        zip_path = tmp_path / "diag.zip"
        build_diagnostic_zip(
            target=zip_path,
            log_path=log_path,
            traceback_text="",
            system_info=SAMPLE_SYSTEM_INFO,
            firstboot_config=cfg,
            include_psk=False,
        )
        with zipfile.ZipFile(zip_path) as zf:
            out = json.loads(zf.read("firstboot_config.json"))
        assert "NestedSecret!" not in json.dumps(out)
        # ssid is not sensitive
        assert out["hotspot"]["ssid"] == "Bootstrap_1234"


# ---------------------------------------------------------------------------
# collect_system_info
# ---------------------------------------------------------------------------


class TestCollectSystemInfo:
    def test_returns_dict(self) -> None:
        info = collect_system_info()
        assert isinstance(info, dict)

    def test_required_keys_present(self) -> None:
        info = collect_system_info()
        for key in ("os", "arch", "python", "app_version"):
            assert key in info, f"Missing key: {key}"

    def test_no_username_in_info(self) -> None:
        """system_info must never expose the OS username."""
        import os

        username = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        info = collect_system_info()
        dumped = json.dumps(info)
        if username:
            assert username not in dumped, f"Username '{username}' leaked into system_info"

    def test_no_computername_in_info(self) -> None:
        """system_info must never expose the computer name / hostname."""
        import os
        import socket

        hostname = os.environ.get("COMPUTERNAME") or ""
        if not hostname:
            try:
                hostname = socket.gethostname()
            except Exception:
                hostname = ""
        info = collect_system_info()
        dumped = json.dumps(info)
        if hostname:
            assert hostname not in dumped, f"Hostname '{hostname}' leaked into system_info"
