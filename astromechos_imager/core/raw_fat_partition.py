"""RawFatBootPartition — userspace FAT32 customize over a raw device.

Satisfies the ``core.platform_io.BootPartition`` Protocol (write_bytes /
read_bytes / mkdir / exists / close) by driving ``pyfatfs`` directly on a
raw ``\\.\PHYSICALDRIVEn`` handle through a ``RawSectorFile`` window — it
NEVER asks Windows to mount the partition.

This is the structural fix for the "Format K:?" / "K:\ is not accessible"
shell pop-ups: those fire because the current ``DriveLetterBootPartition``
forces a Windows mount (SetVolumeMountPointW + a drive letter). pyfatfs
parsing + writing the FAT in userspace means Windows never sees a mounted
volume, so Explorer never renders the dialog and never locks the card.

Pairs with the orchestrator writing the deferred MBR (first block) LAST —
while the MBR is absent, Windows can't even discover the partition to
auto-mount it, so the whole customize window is pop-up-free (the
rpi-imager ordering: image → userspace-FAT customize → MBR last).
"""
from __future__ import annotations

import datetime
import sys


def _import_pyfatfs_classes():
    """Import PyFat + PyFatFS with the pkg_resources shim (Py 3.14 lacks it)."""
    if "pkg_resources" not in sys.modules:
        import types
        stub = types.ModuleType("pkg_resources")
        stub.declare_namespace = lambda _n: None  # type: ignore[attr-defined]
        sys.modules["pkg_resources"] = stub
    from pyfatfs import FAT_OEM_ENCODING
    from pyfatfs.PyFat import PyFat
    from pyfatfs.PyFatFS import PyFatFS
    return PyFat, PyFatFS, FAT_OEM_ENCODING


class RawFatBootPartition:
    """BootPartition impl that writes the FAT in userspace (no mount).

    Parameters
    ----------
    raw_device:
        Object exposing ``read(offset, length) -> bytes`` and
        ``write(offset, data) -> int`` (sector-aligned) + ``flush()``.
        Typically ``platform.windows._Win32RawDevice`` opened WITHOUT
        FILE_FLAG_NO_BUFFERING (so ctypes buffers needn't be page-aligned;
        sector-aligned offset/length is still honoured by RawSectorFile).
    part_start, part_len:
        FAT32 partition window, from ``find_first_fat32_partition``.
    """

    @classmethod
    def open_on_drive(cls, platform_io, physical_drive_id: int,
                      part_start: int, part_len: int) -> "RawFatBootPartition":
        """Open a plain raw handle on ``physical_drive_id`` and own it.

        The returned partition closes the handle on ``.close()``. Used by
        the orchestrator so the FAT customize never has to juggle the
        device lifetime itself.
        """
        dev = platform_io.open_plain_raw_device(physical_drive_id)
        try:
            return cls(dev, part_start, part_len, _owns_device=True)
        except Exception:
            try:
                dev.close()
            except Exception:
                pass
            raise

    def __init__(self, raw_device, part_start: int, part_len: int,
                 _owns_device: bool = False):
        from astromechos_imager.core.raw_sector_io import RawSectorFile
        PyFat, PyFatFS, FAT_OEM_ENCODING = _import_pyfatfs_classes()

        self._owns_device = _owns_device
        self._device = raw_device
        raw_file = RawSectorFile(raw_device, part_start, part_len)

        # Build a PyFatFS but inject our file object via set_fp instead of
        # letting it open() a path (the raw device isn't openable by name).
        # Replicates PyFatFS.__init__ minus the self.fs.open() call.
        pfs = PyFatFS.__new__(PyFatFS)
        import fs.base  # pyfilesystem2 base
        fs.base.FS.__init__(pfs)
        pfs.preserve_case = True
        pfs.fs = PyFat(encoding=FAT_OEM_ENCODING, offset=0, lazy_load=True)
        pfs.fs.set_fp(raw_file)          # parse BPB + FAT from the raw window
        pfs.fs.is_read_only = False
        pfs.tz = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

        self._pfs = pfs
        self._raw_file = raw_file

    # ── BootPartition Protocol ────────────────────────────────────────
    def write_bytes(self, path: str, data: bytes) -> None:
        self._pfs.writebytes(path, data)

    def read_bytes(self, path: str) -> bytes:
        return self._pfs.readbytes(path)  # type: ignore[no-any-return]

    def mkdir(self, path: str) -> None:
        self._pfs.makedirs(path, recreate=True)

    def exists(self, path: str) -> bool:
        return self._pfs.exists(path)  # type: ignore[no-any-return]

    def close(self) -> None:
        # PyFatFS.close() flushes the FAT + marks the volume clean, then
        # closes our RawSectorFile (which flushes its dirty sectors to the
        # device). When we opened the device ourselves (open_on_drive),
        # close it too so the FlushFileBuffers lands and the handle frees.
        try:
            self._pfs.close()
        except Exception:
            pass
        if self._owns_device:
            try:
                self._device.flush()
            except Exception:
                pass
            try:
                self._device.close()
            except Exception:
                pass
        # We have intentionally torn everything down. pyfatfs keeps GC
        # finalizers (PyFat.__del__ / fs.base.FS.__del__) that re-run
        # close() -> our RawSectorFile.flush() at interpreter shutdown; if
        # self._pfs.close() above raised early the sector file was never
        # marked closed, so that finalizer would try to write a dirty
        # sector to the now-closed device handle and print a harmless but
        # noisy "Exception ignored in __del__ ... SetFilePointerEx failed".
        # Force the closed marker so the finalizer short-circuits. Safe: the
        # device is already gone, there is nothing left to flush.
        try:
            self._raw_file._closed = True
        except Exception:
            pass
