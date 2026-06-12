"""Builds a tiny Pi OS-shaped SD image for AstromechOS Imager E2E tests.

Requires WSL on Windows (for mkfs.ext4 and debugfs).
Idempotent: if the fixture exists and the MBR signature + partition table
look correct, returns immediately without rebuilding.

Layout (~96 MB sparse image):
  MBR partition 1: FAT32 boot  at sector  2048, size 16 MiB
  MBR partition 2: ext4 rootfs at sector 34816, size 80 MiB

FAT32 boot pre-populated with a stock Pi OS-like /cmdline.txt.
ext4 rootfs pre-populated with /etc/passwd, /etc/shadow, /etc/group
(root + pi UID 1000) and /home/pi/welcome.txt via WSL debugfs.
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
import types
from pathlib import Path

# ── constants ────────────────────────────────────────────────────────────────

SECTOR = 512

BOOT_START_LBA = 2048
BOOT_SIZE_MIB = 64   # 64 MiB minimum for pyfatfs FAT32 cluster geometry
BOOT_SIZE_LBA = BOOT_SIZE_MIB * 1024 * 1024 // SECTOR  # 131072 sectors

ROOTFS_START_LBA = BOOT_START_LBA + BOOT_SIZE_LBA        # 133120
ROOTFS_SIZE_MIB = 32
ROOTFS_SIZE_LBA = ROOTFS_SIZE_MIB * 1024 * 1024 // SECTOR  # 65536 sectors

BOOT_OFFSET = BOOT_START_LBA * SECTOR       # 1 048 576 bytes
BOOT_SIZE = BOOT_SIZE_LBA * SECTOR          # 67 108 864 bytes
ROOTFS_OFFSET = ROOTFS_START_LBA * SECTOR   # 68 157 440 bytes
ROOTFS_SIZE = ROOTFS_SIZE_LBA * SECTOR      # 33 554 432 bytes
TOTAL_SIZE = ROOTFS_OFFSET + ROOTFS_SIZE    # 101 711 872 bytes (~97 MiB sparse)

STOCK_CMDLINE = (
    "console=serial0,115200 console=tty1 root=PARTUUID=6c586e13-02 "
    "rootfstype=ext4 fsck.repair=yes rootwait quiet splash\n"
)

_PASSWD = (
    "root:x:0:0:root:/root:/bin/bash\n"
    "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
    "pi:x:1000:1000:,,,:/home/pi:/bin/bash\n"
)
_SHADOW = (
    "root:*:19000:0:99999:7:::\n"
    "daemon:*:19000:0:99999:7:::\n"
    "pi:DUMMYHASH:19000:0:99999:7:::\n"
)
_GROUP = (
    "root:x:0:\n"
    "daemon:x:1:\n"
    "pi:x:1000:\n"
    "sudo:x:27:pi\n"
    "adm:x:4:pi\n"
)
_WELCOME = "hello from pi\n"


# ── helpers ──────────────────────────────────────────────────────────────────


def _win_to_wsl(p: Path) -> str:
    """Translate a Windows absolute path to its WSL /mnt/<drive>/... form."""
    p = Path(p).resolve()
    drive = p.drive.rstrip(":").lower()
    rest = str(p).split(":", 1)[1].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


def _wsl_run(args: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run a command via WSL, capturing output."""
    return subprocess.run(["wsl", *args], capture_output=True, text=True, check=check, **kwargs)


def _stub_pkg_resources() -> None:
    if "pkg_resources" not in sys.modules:
        stub = types.ModuleType("pkg_resources")
        stub.declare_namespace = lambda _name: None  # type: ignore[attr-defined]
        sys.modules["pkg_resources"] = stub


def _make_mbr() -> bytes:
    """Build a 512-byte MBR with the Pi OS partition layout."""
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xAA"

    # Partition 1: FAT32 LBA (0x0C)
    e0 = bytearray(16)
    e0[4] = 0x0C
    struct.pack_into("<I", e0, 8, BOOT_START_LBA)
    struct.pack_into("<I", e0, 12, BOOT_SIZE_LBA)
    mbr[446:462] = bytes(e0)

    # Partition 2: Linux ext4 (0x83)
    e1 = bytearray(16)
    e1[4] = 0x83
    struct.pack_into("<I", e1, 8, ROOTFS_START_LBA)
    struct.pack_into("<I", e1, 12, ROOTFS_SIZE_LBA)
    mbr[462:478] = bytes(e1)

    return bytes(mbr)


def _fixture_looks_valid(path: Path) -> bool:
    """Quick sanity check: MBR signature + correct partition types."""
    if not path.exists():
        return False
    if path.stat().st_size < ROOTFS_OFFSET + 512:
        return False
    with path.open("rb") as fh:
        mbr = fh.read(512)
    if mbr[510:512] != b"\x55\xAA":
        return False
    # Partition 1 must be FAT32 (0x0C)
    if mbr[446 + 4] != 0x0C:
        return False
    # Partition 2 must be Linux (0x83)
    if mbr[462 + 4] != 0x83:
        return False
    return True


def _format_boot_fat32(img_path: Path) -> None:
    """Format the boot partition region in img_path as FAT32 via pyfatfs."""
    _stub_pkg_resources()
    from pyfatfs.PyFat import PyFat  # noqa: PLC0415

    pf = PyFat(offset=BOOT_OFFSET)
    try:
        pf.mkfs(str(img_path), PyFat.FAT_TYPE_FAT32, size=BOOT_SIZE)
    finally:
        try:
            pf.close()
        except Exception:
            pass


def _write_boot_files(img_path: Path) -> None:
    """Write /cmdline.txt to the FAT32 boot partition via pyfatfs."""
    _stub_pkg_resources()
    from astromechos_imager.core.bootpartition import BootPartitionLayout  # noqa: PLC0415

    layout = BootPartitionLayout(
        offset=BOOT_OFFSET,
        size=BOOT_SIZE,
        partition_type=0x0C,
    )
    from astromechos_imager.core.bootpartition import PyFatFsBootPartition  # noqa: PLC0415
    bp = PyFatFsBootPartition(str(img_path), layout)
    try:
        bp.write_bytes("/cmdline.txt", STOCK_CMDLINE.encode("ascii"))
    finally:
        bp.close()


def _format_rootfs_ext4(img_path: Path) -> None:
    """Format the rootfs partition as ext4 via WSL mkfs.ext4.

    Uses mkfs.ext4's ``-E offset=N`` extended option to target the partition
    region within the combined image. The filesystem size in 4096-byte blocks
    is passed as a positional argument so mkfs does not extend past the partition.
    """
    wsl_path = _win_to_wsl(img_path)
    # 4096-byte blocks: ROOTFS_SIZE / 4096
    rootfs_blocks = ROOTFS_SIZE // 4096
    _wsl_run([
        "mkfs.ext4", "-q", "-F",
        "-b", "4096",
        "-E", f"offset={ROOTFS_OFFSET}",
        wsl_path,
        str(rootfs_blocks),
    ])


def _populate_rootfs_ext4(img_path: Path) -> None:
    """Populate the ext4 rootfs with /etc/passwd, shadow, group, /home/pi via WSL debugfs.

    Writes source files to a Windows temp directory (accessible from both Windows
    and WSL via /mnt/...), then uses debugfs scripted commands to inject them
    into the ext4 partition at the correct offset.
    """

    wsl_path = _win_to_wsl(img_path)
    device_arg = f"{wsl_path}?offset={ROOTFS_OFFSET}"

    # Write source files to a Windows temp dir that WSL can access via /mnt/...
    with tempfile.TemporaryDirectory(prefix="astro-fixture-") as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "passwd").write_text(_PASSWD, encoding="utf-8", newline="\n")
        (tmp / "shadow").write_text(_SHADOW, encoding="utf-8", newline="\n")
        (tmp / "group").write_text(_GROUP, encoding="utf-8", newline="\n")
        (tmp / "welcome.txt").write_text(_WELCOME, encoding="utf-8", newline="\n")

        # debugfs script — uses WSL paths for the source files
        wsl_tmp = _win_to_wsl(tmp)
        script_lines = [
            "mkdir /etc",
            "mkdir /home",
            "mkdir /home/pi",
            f"write {wsl_tmp}/passwd /etc/passwd",
            f"write {wsl_tmp}/shadow /etc/shadow",
            f"write {wsl_tmp}/group /etc/group",
            f"write {wsl_tmp}/welcome.txt /home/pi/welcome.txt",
            "quit",
            "",
        ]
        script_path = tmp / "cmds.txt"
        script_path.write_text("\n".join(script_lines), encoding="utf-8", newline="\n")
        wsl_script = _win_to_wsl(script_path)

        _wsl_run(["debugfs", "-w", "-f", wsl_script, device_arg])


# ── public API ───────────────────────────────────────────────────────────────


def build_pi_os_fixture(out_path: Path, force: bool = False) -> Path:
    """Build (or verify) the Pi OS-shaped fixture image.

    This function is idempotent: if *out_path* already looks like a valid
    Pi OS MBR image with the expected partition layout, it returns immediately
    without rebuilding. Pass ``force=True`` to force a rebuild.

    Parameters
    ----------
    out_path:
        Absolute path where the fixture image should be created.
        The parent directory must exist.
    force:
        If True, delete and rebuild even if the fixture already exists.

    Returns
    -------
    Path
        The path to the fixture image (same as *out_path*).

    Raises
    ------
    RuntimeError
        If WSL is not available or fixture creation fails.
    """
    if not force and _fixture_looks_valid(out_path):
        return out_path

    if shutil.which("wsl") is None:
        raise RuntimeError(
            "WSL is required to build the AstromechOS Imager Pi OS-shaped fixture. "
            "Install WSL or use the pre-built fixture."
        )

    if force and out_path.exists():
        out_path.unlink()

    # 1. Create sparse file and write MBR
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        fh.seek(TOTAL_SIZE - 1)
        fh.write(b"\x00")
    with out_path.open("r+b") as fh:
        fh.write(_make_mbr())

    # 2. Format FAT32 boot partition via pyfatfs
    try:
        _format_boot_fat32(out_path)
    except Exception as exc:
        raise RuntimeError(f"FAT32 format failed: {exc}") from exc

    # 3. Write /cmdline.txt to FAT32 partition
    try:
        _write_boot_files(out_path)
    except Exception as exc:
        raise RuntimeError(f"Boot file write failed: {exc}") from exc

    # 4. Format ext4 rootfs partition via WSL
    try:
        _format_rootfs_ext4(out_path)
    except Exception as exc:
        raise RuntimeError(f"ext4 format failed: {exc}") from exc

    # 5. Populate rootfs via WSL debugfs
    try:
        _populate_rootfs_ext4(out_path)
    except Exception as exc:
        raise RuntimeError(f"ext4 populate failed: {exc}") from exc

    return out_path


if __name__ == "__main__":
    """Allow running as: python -m tests.fixtures.make_pi_os_fixture [--force]"""
    import argparse

    parser = argparse.ArgumentParser(description="Build Pi OS-shaped AstromechOS test fixture")
    parser.add_argument("--force", action="store_true", help="Rebuild even if fixture exists")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "pi_os_shaped.img",
        help="Output image path",
    )
    args = parser.parse_args()
    result = build_pi_os_fixture(args.out, force=args.force)
    print(f"Fixture ready: {result}")
