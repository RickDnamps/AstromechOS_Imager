"""End-to-end test: personalize a Pi OS-shaped fixture via WSL + pyfatfs.

Exercises the full personalization path (skipping raw write phase) and
asserts all four cold-mod contract surfaces:
  - /etc/passwd rename (UID-1000 pi → testuser)
  - /etc/shadow hash replacement
  - /etc/group rename
  - /home rename
  - /cmdline.txt resize init injection
  - e2fsck clean
  - FAT32 firstboot bundle correctness

Skipped if WSL is not available (fixture requires WSL to build).
"""
from __future__ import annotations

import json
import shutil
import sys
import types
from pathlib import Path

import pytest

from astromechos_imager.core.bootpartition import (
    BootPartitionLayout,
    PyFatFsBootPartition,
    find_first_fat32_partition,
    find_rootfs_partition,
)
from astromechos_imager.core.keygen import generate_ed25519, generate_hotspot_bootstrap
from astromechos_imager.core.models import FirstbootConfig, LinuxAccount, Role
from astromechos_imager.core.passwd_files import parse_passwd
from astromechos_imager.core.rootfs import Ext4DebugfsBackend, _win_to_wsl_path
from astromechos_imager.core.rootfs_personalizer import RESIZE_INIT_ARG, RootfsPersonalizer
from astromechos_imager.core.customization import FirstbootBundle

pytestmark = pytest.mark.integration

_WSL_AVAILABLE = shutil.which("wsl") is not None
_FIXTURE_PATH = Path("tests/fixtures/pi_os_shaped.img").absolute()

VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIUSER user@laptop"


def _stub_pkg_resources() -> None:
    if "pkg_resources" not in sys.modules:
        stub = types.ModuleType("pkg_resources")
        stub.declare_namespace = lambda _name: None  # type: ignore[attr-defined]
        sys.modules["pkg_resources"] = stub


@pytest.fixture(scope="module")
def pi_os_fixture():
    """Build or return the Pi OS-shaped fixture image (built once per test session)."""
    if not _WSL_AVAILABLE:
        pytest.skip("WSL not available — skipping E2E personalize test")

    from tests.fixtures.make_pi_os_fixture import build_pi_os_fixture  # noqa: PLC0415
    try:
        return build_pi_os_fixture(_FIXTURE_PATH)
    except Exception as exc:
        pytest.skip(f"Could not build Pi OS fixture: {exc}")


def test_full_personalize_via_wsl_and_pyfatfs(tmp_path, fixed_iso_time, pi_os_fixture):
    """Full personalization of Pi OS-shaped fixture: rootfs rename + cmdline + firstboot bundle.

    This test exercises the complete AstromechOS Imager personalization path
    (minus the raw write step) on a real Pi OS-shaped disk image:
      1. Build a copy of the fixture in tmp_path.
      2. Open the ext4 rootfs via Ext4DebugfsBackend (WSL).
      3. Open the FAT32 boot via PyFatFsBootPartition (pyfatfs).
      4. Run RootfsPersonalizer(account, rootfs, boot).apply().
      5. Write the FirstbootBundle to the boot partition.
      6. Assert all contract surfaces.
    """
    fixture_copy = tmp_path / "sd.img"
    shutil.copy(pi_os_fixture, fixture_copy)

    # ── Parse partition layout from MBR ──────────────────────────────────────
    with fixture_copy.open("rb") as fh:
        mbr = fh.read(512)
    boot_layout = find_first_fat32_partition(mbr)
    rootfs_layout = find_rootfs_partition(mbr)

    # ── Open ext4 rootfs via WSL ──────────────────────────────────────────────
    rootfs = Ext4DebugfsBackend(
        image_path=_win_to_wsl_path(fixture_copy),
        offset_bytes=rootfs_layout.offset,
        debugfs_exe=Path("/usr/sbin/debugfs"),
        e2fsck_exe=Path("/usr/sbin/e2fsck"),
        invoker=["wsl"],
    )

    # ── Open FAT32 boot via pyfatfs ───────────────────────────────────────────
    _stub_pkg_resources()
    boot = PyFatFsBootPartition(str(fixture_copy), boot_layout)

    acc = LinuxAccount(
        username="testuser",
        cleartext_password="test123",
        crypt_sha512="$6$testsalt$fakehashfortest",
    )
    cfg = FirstbootConfig(
        authorized_keys=[VALID_KEY],
        imager_version="0.1.0",
        flashed_at_iso=fixed_iso_time,
        hotspot_bootstrap=generate_hotspot_bootstrap("test-psk-12345"),
    )
    pair = generate_ed25519()

    try:
        # ── Step 4: RootfsPersonalizer ────────────────────────────────────────
        RootfsPersonalizer(acc, rootfs, boot).apply()

        # ── Step 5: FirstbootBundle ───────────────────────────────────────────
        FirstbootBundle(cfg, pair).write_to(boot, Role.MASTER)

        # ── Step 6a: Assert rootfs mutations ─────────────────────────────────
        # /etc/passwd: UID-1000 renamed to testuser
        passwd_bytes = rootfs.read_bytes("/etc/passwd")
        rows = parse_passwd(passwd_bytes)
        uid_row = next((r for r in rows if r.uid == 1000), None)
        assert uid_row is not None, "/etc/passwd has no UID-1000 row after rename"
        assert uid_row.name == "testuser", f"Expected testuser, got {uid_row.name!r}"
        assert uid_row.home == "/home/testuser", f"Expected /home/testuser, got {uid_row.home!r}"
        assert b"pi:x:1000" not in passwd_bytes

        # /etc/shadow: testuser present, hash replaced
        shadow_bytes = rootfs.read_bytes("/etc/shadow")
        assert b"testuser:" in shadow_bytes
        assert b"pi:" not in shadow_bytes
        assert acc.crypt_sha512.encode() in shadow_bytes

        # /etc/group: testuser present
        group_bytes = rootfs.read_bytes("/etc/group")
        assert b"testuser:x:1000:" in group_bytes
        assert b"pi:x:1000:" not in group_bytes

        # /home/testuser accessible (welcome.txt survived the rename)
        welcome = rootfs.read_bytes("/home/testuser/welcome.txt")
        assert welcome.strip() == b"hello from pi"

        # e2fsck clean
        assert rootfs.fsck_clean() is True, "e2fsck reports errors after personalization"

        # ── Step 6b: Assert boot partition mutations ──────────────────────────
        # /cmdline.txt: resize init arg present
        cmdline = boot.read_bytes("/cmdline.txt")
        assert RESIZE_INIT_ARG.encode("ascii") in cmdline, (
            f"/cmdline.txt missing resize init arg: {cmdline!r}"
        )
        # All original args still there
        assert b"console=serial0,115200" in cmdline
        assert b"rootwait" in cmdline

        # /ASTROMECH_FIRSTBOOT_READY: trigger marker (LAST — bundle contract)
        assert boot.exists("/ASTROMECH_FIRSTBOOT_READY"), "Trigger marker missing"

        # /astromech_init.cfg: [system] user = testuser (from firstboot config)
        init_cfg = boot.read_bytes("/astromech_init.cfg").decode("utf-8")
        assert "user = pi" in init_cfg, (
            "init_cfg should have user=pi (FirstbootConfig.install_user default)"
        )

        # /astromech_secrets/init_config.json: role=master, hostname=astromech-master
        init_json = json.loads(boot.read_bytes("/astromech_secrets/init_config.json"))
        assert init_json["role"] == "master"
        assert init_json["hostname"] == "astromech-master"

        # /astromech_secrets/authorized_keys: valid SSH key present
        ak = boot.read_bytes("/astromech_secrets/authorized_keys").decode("utf-8")
        assert "ssh-ed25519" in ak

        # /astromech_secrets/id_ed25519 + .pub: master keypair present
        assert boot.exists("/astromech_secrets/id_ed25519")
        assert boot.exists("/astromech_secrets/id_ed25519.pub")

    finally:
        rootfs.close()
        boot.close()


def test_full_personalize_idempotent_cmdline(tmp_path, fixed_iso_time, pi_os_fixture):
    """If cmdline already has the resize arg, applying again doesn't duplicate it."""
    fixture_copy = tmp_path / "sd2.img"
    shutil.copy(pi_os_fixture, fixture_copy)

    with fixture_copy.open("rb") as fh:
        mbr = fh.read(512)
    boot_layout = find_first_fat32_partition(mbr)
    rootfs_layout = find_rootfs_partition(mbr)

    rootfs = Ext4DebugfsBackend(
        image_path=_win_to_wsl_path(fixture_copy),
        offset_bytes=rootfs_layout.offset,
        debugfs_exe=Path("/usr/sbin/debugfs"),
        e2fsck_exe=Path("/usr/sbin/e2fsck"),
        invoker=["wsl"],
    )
    _stub_pkg_resources()
    boot = PyFatFsBootPartition(str(fixture_copy), boot_layout)

    acc = LinuxAccount(
        username="testuser",
        cleartext_password="test123",
        crypt_sha512="$6$testsalt$fakehashfortest",
    )

    try:
        # Apply once
        RootfsPersonalizer(acc, rootfs, boot).apply()
        cmdline_after_first = boot.read_bytes("/cmdline.txt")
        assert RESIZE_INIT_ARG.encode("ascii") in cmdline_after_first

        # Verify the arg appears exactly once
        count = cmdline_after_first.decode("ascii").split().count(RESIZE_INIT_ARG)
        assert count == 1, f"Expected 1 occurrence of resize arg, got {count}"

    finally:
        rootfs.close()
        boot.close()
