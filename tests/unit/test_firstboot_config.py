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
