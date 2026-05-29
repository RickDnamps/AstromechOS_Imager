"""ext4 rootfs accessor — wraps debugfs subprocess.

``Ext4DebugfsBackend`` implements the ``RootfsPartition`` Protocol defined in
``core/platform_io.py``.  In production the ``debugfs_exe`` and ``e2fsck_exe``
paths point to bundled Windows executables.  In dev/test on a Windows + WSL
machine, pass ``invoker=["wsl"]`` and use the WSL paths
``/usr/sbin/debugfs`` / ``/usr/sbin/e2fsck``.
"""
from __future__ import annotations

import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

from astromechos_imager.core.errors import RootfsModError


# ─────────────────────────────────────────────────────────────────────────────
# Path translation helpers
# ─────────────────────────────────────────────────────────────────────────────


def _win_to_wsl_path(p: Path) -> str:
    """Translate a Windows absolute path to its WSL ``/mnt/<drive>/...`` equivalent.

    Example::

        _win_to_wsl_path(Path("J:/Foo/Bar.img")) == "/mnt/j/Foo/Bar.img"
    """
    p = Path(p).resolve()
    drive = p.drive.rstrip(":").lower()         # "J:" → "j"
    rest = str(p).split(":", 1)[1].replace("\\", "/")  # ":/Foo/Bar.img" → "/Foo/Bar.img"
    return f"/mnt/{drive}{rest}"


# ─────────────────────────────────────────────────────────────────────────────
# Backend
# ─────────────────────────────────────────────────────────────────────────────


class Ext4DebugfsBackend:
    """ext4 filesystem accessor via ``debugfs`` subprocess.

    Parameters
    ----------
    image_path:
        Path to the ext4 image file (or raw block device).  On WSL invocations
        this should already be a POSIX path (``/mnt/j/...``).
    offset_bytes:
        Byte offset into *image_path* where the ext4 partition starts.
        Pass ``0`` when pointing directly at an ext4 image file.
    debugfs_exe:
        Path to the ``debugfs`` executable.
    e2fsck_exe:
        Path to the ``e2fsck`` executable.
    temp_dir:
        Optional persistent temp directory.  Created automatically if *None*;
        ``close()`` removes it.
    invoker:
        Optional command prefix prepended before ``debugfs_exe``.  Use
        ``["wsl"]`` on Windows to route the call through WSL.
    """

    def __init__(
        self,
        image_path: str,
        offset_bytes: int,
        debugfs_exe: Path,
        e2fsck_exe: Path,
        temp_dir: Path | None = None,
        invoker: list[str] | None = None,
    ) -> None:
        self.image = image_path
        self.offset = offset_bytes
        self.debugfs = debugfs_exe
        self.e2fsck = e2fsck_exe
        self.temp = temp_dir or Path(tempfile.mkdtemp(prefix="astro-rootfs-"))
        self.invoker: list[str] = invoker or []

    # ── Internal helpers ──────────────────────────────────────────────────

    def _device_arg(self) -> str:
        if self.offset:
            return f"{self.image}?offset={self.offset}"
        return self.image

    def _debugfs_str(self) -> str:
        """Return the debugfs path as a string usable by the subprocess.

        When routing through WSL (``invoker=["wsl"]``), the debugfs path is a
        POSIX path (``/usr/sbin/debugfs``).  On Windows, ``Path("/usr/sbin/…")``
        gets its backslash mangled, so we preserve the original string form of
        the ``Path`` using ``self.debugfs.as_posix()``.
        """
        if self.invoker and self.invoker[0] == "wsl":
            return self.debugfs.as_posix()
        return str(self.debugfs)

    def _e2fsck_str(self) -> str:
        """Return the e2fsck path as a string usable by the subprocess."""
        if self.invoker and self.invoker[0] == "wsl":
            return self.e2fsck.as_posix()
        return str(self.e2fsck)

    def _cmd(self, *trailing: str) -> list[str]:
        return [*self.invoker, self._debugfs_str(), *trailing]

    def _to_guest_path(self, host_path: Path) -> str:
        """Return the path as seen by the subprocess (WSL or native)."""
        if self.invoker and self.invoker[0] == "wsl":
            return _win_to_wsl_path(host_path)
        return str(host_path)

    def _run_debugfs_script(self, commands: list[str]) -> str:
        """Write *commands* + ``quit`` to a temp script file and run debugfs.

        Returns
        -------
        str
            The combined stdout of the debugfs process.
        """
        script = self.temp / f"cmds-{secrets.token_hex(4)}.txt"
        script.write_text("\n".join([*commands, "quit", ""]), encoding="utf-8")
        script_arg = self._to_guest_path(script)

        cmd = self._cmd("-w", "-f", script_arg, self._device_arg())
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout

    # ── RootfsPartition interface ─────────────────────────────────────────

    def read_bytes(self, path: str) -> bytes:
        """Dump *path* from the ext4 image to a temp file and return its bytes."""
        out = self.temp / f"dump-{secrets.token_hex(4)}.bin"
        out_arg = self._to_guest_path(out)
        self._run_debugfs_script([f"dump {path} {out_arg}"])
        return out.read_bytes()

    def write_bytes(self, path: str, data: bytes) -> None:
        """Write *data* to *path* inside the ext4 image.

        The existing inode (if any) is removed first so the write command
        creates a fresh inode with the new content.
        """
        src = self.temp / f"src-{secrets.token_hex(4)}.bin"
        src.write_bytes(data)
        src_arg = self._to_guest_path(src)

        # Remove any existing file — ignore failures (file may not exist).
        try:
            self._run_debugfs_script([f"rm {path}"])
        except subprocess.CalledProcessError:
            pass

        self._run_debugfs_script([f"write {src_arg} {path}"])

    def rename(self, src: str, dst: str) -> None:
        """Rename *src* to *dst* inside the ext4 image (inode preserved).

        Implemented as ``link <src> <dst>`` + ``unlink <src>``, which works for
        both regular files and directories.
        """
        try:
            self._run_debugfs_script([f"link {src} {dst}", f"unlink {src}"])
        except subprocess.CalledProcessError as exc:
            raise RootfsModError(
                f"rename {src!r} → {dst!r} failed: {exc.stderr or exc}"
            ) from exc

    def fsck_clean(self) -> bool:
        """Run ``e2fsck -fn`` and return *True* iff the filesystem is clean."""
        cmd = [*self.invoker, self._e2fsck_str(), "-fn", self._device_arg()]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0

    def close(self) -> None:
        """Remove the temporary directory created during construction."""
        shutil.rmtree(self.temp, ignore_errors=True)
