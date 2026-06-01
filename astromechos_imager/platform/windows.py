"""Windows platform IO. Per design spec §5.1-5.2.

ONLY this module imports Win32 APIs. Everything else routes through
core/platform_io.py Protocols.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import time
from ctypes import wintypes
from typing import Iterator

from astromechos_imager.core.models import DiskRef

_log = logging.getLogger(__name__)

_MAX_SD_BYTES = 256 * 1024 * 1024 * 1024   # hard cap — no R2 build needs > 256 GB
_PHYS_DRIVE_RE = re.compile(r"PHYSICALDRIVE(\d+)", re.IGNORECASE)


def _wmi_query() -> list:
    """Query Win32_DiskDrive via WMI. Indirected for monkeypatching in tests."""
    import win32com.client  # pywin32
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    q = ("SELECT DeviceID, Size, Model, SerialNumber, InterfaceType, MediaType "
         "FROM Win32_DiskDrive")
    return list(wmi.ExecQuery(q))


def _drive_letters_for(device_id: str) -> tuple[str, ...]:
    """Resolve drive letters mounted on a Win32_DiskDrive via the partition graph."""
    import win32com.client
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    letters: list[str] = []
    parts = wmi.ExecQuery(
        f"ASSOCIATORS OF {{Win32_DiskDrive.DeviceID='{device_id}'}} "
        "WHERE AssocClass=Win32_DiskDriveToDiskPartition"
    )
    for part in parts:
        logicals = wmi.ExecQuery(
            f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{part.DeviceID}'}} "
            "WHERE AssocClass=Win32_LogicalDiskToPartition"
        )
        for logical in logicals:
            if logical.DeviceID:
                letters.append(logical.DeviceID.rstrip(":"))
    return tuple(letters)


def _system_drive_id() -> int:
    """Return the PhysicalDriveN number that hosts %SystemDrive% (e.g. C:)."""
    sys_letter = os.environ.get("SystemDrive", "C:").rstrip(":")
    import win32com.client
    wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
    for ld in wmi.ExecQuery(f"SELECT * FROM Win32_LogicalDisk WHERE DeviceID='{sys_letter}:'"):
        parts = wmi.ExecQuery(
            f"ASSOCIATORS OF {{Win32_LogicalDisk.DeviceID='{ld.DeviceID}'}} "
            "WHERE AssocClass=Win32_LogicalDiskToPartition"
        )
        for part in parts:
            drives = wmi.ExecQuery(
                f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{part.DeviceID}'}} "
                "WHERE AssocClass=Win32_DiskDriveToDiskPartition"
            )
            for drive in drives:
                m = _PHYS_DRIVE_RE.search(drive.DeviceID)
                if m:
                    return int(m.group(1))
    return -1


def enumerate_removable_drives() -> Iterator[DiskRef]:
    """Yield only safe removable candidates. Refs design spec §5.1.

    Every WMI candidate's accept/reject decision is logged at INFO so a
    legitimate SD card sitting behind a USB-SATA bridge (JMicron etc.) that
    misreports as ``InterfaceType=SCSI`` + ``MediaType="Fixed hard disk
    media"`` becomes visible in the session log instead of silently
    disappearing into the filter.
    """
    sys_id = _system_drive_id()
    candidates = list(_wmi_query())
    _log.info(
        "enumerate_removable_drives: WMI returned %d candidate disk(s)",
        len(candidates),
    )
    for d in candidates:
        device_id = d.DeviceID or "<no-DeviceID>"
        interface = (d.InterfaceType or "").upper()
        media = d.MediaType or ""
        is_usb = interface == "USB"
        is_removable = "removable" in media.lower()
        if not (is_usb or is_removable):
            _log.info(
                "  reject %s: interface=%s media=%r (not USB and not removable)",
                device_id, interface, media,
            )
            continue
        m = _PHYS_DRIVE_RE.search(device_id)
        if not m:
            _log.info(
                "  reject %s: DeviceID does not match PHYSICALDRIVE regex",
                device_id,
            )
            continue
        phys_id = int(m.group(1))
        if phys_id == sys_id:
            _log.info(
                "  reject %s: phys_id=%d is the system drive",
                device_id, phys_id,
            )
            continue
        size = int(d.Size or 0)
        if size <= 0 or size > _MAX_SD_BYTES:
            _log.info(
                "  reject %s: size=%d outside (0, %d]",
                device_id, size, _MAX_SD_BYTES,
            )
            continue
        _log.info(
            "  ACCEPT %s: phys_id=%d size=%d interface=%s media=%r",
            device_id, phys_id, size, interface, media,
        )
        yield DiskRef(
            physical_drive_id=phys_id,
            device_path=device_id,
            drive_letters=_drive_letters_for(device_id),
            size_bytes=size,
            model=(d.Model or "Unknown").strip(),
            serial=(d.SerialNumber or "").strip(),
        )


# ── Lock / dismount / raw device open ─────────────────────────────────────

from astromechos_imager.core.errors import DriveLockError, DrivePermissionError
from astromechos_imager.platform._win32 import (
    GENERIC_READ, GENERIC_WRITE, FILE_SHARE_READ, FILE_SHARE_WRITE,
    OPEN_EXISTING, FILE_FLAG_NO_BUFFERING, FILE_FLAG_WRITE_THROUGH,
    FILE_FLAG_SEQUENTIAL_SCAN,
    FSCTL_ALLOW_EXTENDED_DASD_IO, FSCTL_LOCK_VOLUME, FSCTL_UNLOCK_VOLUME,
    FSCTL_DISMOUNT_VOLUME, INVALID_HANDLE_VALUE,
    IOCTL_DISK_UPDATE_PROPERTIES, IOCTL_DISK_DELETE_DRIVE_LAYOUT,
    IOCTL_STORAGE_EJECT_MEDIA, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS,
    DISK_GEOMETRY_EX, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, kernel32,
)
import struct as _struct


def _ctl(handle: int, code: int, in_buf: bytes = b"") -> None:
    k = kernel32()
    out = wintypes.DWORD(0)
    ok = k.DeviceIoControl(
        handle, code,
        ctypes.c_char_p(in_buf) if in_buf else None, len(in_buf),
        None, 0, ctypes.byref(out), None,
    )
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"DeviceIoControl(0x{code:08X}) failed (Win32 err {err})")


def _create_volume_handle(letter: str) -> int:
    r"""Open \\.\X: for FSCTL operations. Returns handle or raises."""
    k = kernel32()
    path = f"\\\\.\\{letter}:"
    h = k.CreateFileW(
        path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING, 0, None,
    )
    if h == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        if err == 5:  # ERROR_ACCESS_DENIED
            raise DrivePermissionError(f"Cannot open volume {letter}: (need admin?)")
        raise OSError(err, f"CreateFileW({path}) failed")
    return h


def _delete_mount_point(letter: str) -> bool:
    """Remove the drive-letter assignment via Mount Manager.

    Unlike FSCTL_DISMOUNT_VOLUME (which only unmounts the filesystem
    on a single handle), DeleteVolumeMountPointW removes the drive
    letter entirely from Mount Manager state — Windows can no longer
    re-mount the freshly-written partition under the same letter, so
    it cannot inject ``System Volume Information`` bytes during the
    verify_readback window (audit Bug #0). Pattern borrowed from
    rpi-imager's ``diskpart_util.cpp``.

    Returns True on success, False on failure (caller logs).
    """
    k = kernel32()
    path = f"{letter}:\\"
    ok = bool(k.DeleteVolumeMountPointW(path))
    if not ok:
        err = ctypes.get_last_error()
        _log.info(
            "  DeleteVolumeMountPointW(%s) failed (Win32 err %d) "
            "— continuing anyway",
            path, err,
        )
    else:
        _log.info("  DeleteVolumeMountPointW(%s) OK", path)
    return ok


def _open_volume_handle(open_path: str) -> int:
    """CreateFileW a volume for FSCTL ops. ``open_path`` is ``\\\\.\\X:`` or a
    ``\\?\\Volume{guid}`` (trailing backslash already stripped). Returns the
    handle or INVALID_HANDLE_VALUE."""
    k = kernel32()
    return k.CreateFileW(
        open_path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None,
    )


def lock_and_dismount(letters: tuple[str, ...],
                      physical_drive_id: int | None = None) -> list[int]:
    r"""Lock + dismount every volume on the target and HOLD the locks open.

    This is the Win32DiskImager / rpi-imager approach. The caller MUST keep
    the returned handles open for the ENTIRE write + verify + customize, and
    close them only at the very end (closing a handle releases its
    FSCTL_LOCK_VOLUME, letting Windows remount the freshly-written card).

    Holding the lock for the whole flash is what:
      * stops Windows re-mounting the volume mid-write and re-protecting its
        sectors — the ERROR_ACCESS_DENIED we saw at the FAT32 offset once
        IOCTL_DISK_DELETE_DRIVE_LAYOUT was removed; and
      * stops the "Format K:?" / "not accessible" pop-up — a locked volume
        cannot be mounted by the shell.

    We do NOT clear the partition table (DELETE_DRIVE_LAYOUT) — that forced
    Windows to see the disk go RAW and fired the pop-up. We do NOT delete
    the mount point either — the held lock is the whole mechanism, and the
    letter comes back cleanly when we close the handle at the end.

    Volume discovery: when ``physical_drive_id`` is given we lock by VOLUME
    GUID only (``_list_volumes`` enumerates every volume on the drive,
    lettered or not). We deliberately do NOT also lock by drive letter in
    that case: ``\\.\K:`` and ``\\?\Volume{guid}`` name the SAME volume, and
    a second FSCTL_LOCK_VOLUME on an already-locked volume fails — which used
    to abort the whole flash with a DriveLockError on any card Windows had
    auto-mounted under a letter. Locking by GUID covers the lettered case
    too (the lock is on the volume, not the letter). The ``letters`` list is
    only used as a fallback when ``physical_drive_id`` is None (tests /
    legacy callers that don't pass the drive id).
    """
    open_paths: list[str] = []
    if physical_drive_id is not None:
        try:
            for vol in _list_volumes():           # \\?\Volume{guid}\
                if physical_drive_id in _volume_disk_extents(vol):
                    open_paths.append(vol.rstrip("\\"))
        except Exception as exc:  # noqa: BLE001
            _log.info("volume enumeration for lock failed (%s) — "
                      "falling back to locking by letter", exc)
    if not open_paths:
        # No drive id, or enumeration failed — lock by letter instead.
        for letter in letters:
            open_paths.append(f"\\\\.\\{letter}:")
    _log.info("lock_and_dismount: phys_id=%s letters=%s -> %d volume(s) to lock: %s",
              physical_drive_id, letters, len(open_paths), open_paths)

    held: list[int] = []
    seen: set[str] = set()
    for open_path in open_paths:
        if open_path in seen:
            continue
        seen.add(open_path)
        h = _open_volume_handle(open_path)
        if h == INVALID_HANDLE_VALUE:
            continue   # volume vanished / no media — skip
        locked = False
        last_err = None
        for _attempt in range(8):     # geometric-ish backoff, ~ rpi-imager
            try:
                _ctl(h, FSCTL_LOCK_VOLUME)
                locked = True
                break
            except OSError as e:
                last_err = e
                time.sleep(0.25)
        if not locked:
            # Could not get exclusive access (Explorer / AV / indexer).
            kernel32().CloseHandle(h)
            for prev in held:
                kernel32().CloseHandle(prev)
            raise DriveLockError(
                f"FSCTL_LOCK_VOLUME failed for {open_path} after retries "
                f"(close Explorer / antivirus and retry). Last err: {last_err}"
            )
        try:
            _ctl(h, FSCTL_DISMOUNT_VOLUME)
        except OSError:
            pass   # best-effort; the held lock already blocks remount
        held.append(h)   # KEEP open + locked for the whole flash
        _log.info("  locked + dismounted %s -> handle 0x%X (held)", open_path, h)
    _log.info("lock_and_dismount: holding %d locked handle(s): %s",
              len(held), [hex(x) for x in held])
    return held


def open_raw_device(physical_drive_id: int) -> int:
    r"""Open \\.\PHYSICALDRIVEn for raw read+write. Returns handle or raises.

    Enables FSCTL_ALLOW_EXTENDED_DASD_IO on the handle (rpi-imager
    ``file_operations_windows.cpp:349``) so subsequent writes can land in
    ANY sector of the physical drive — without this, Windows filters
    writes to sectors that fall within a recognised partition and returns
    ERROR_ACCESS_DENIED at the partition's start offset.
    """
    k = kernel32()
    path = f"\\\\.\\PHYSICALDRIVE{physical_drive_id}"
    # rpi-imager's OpenDevice flag set for physical drives
    # (file_operations_windows.cpp:286): NO_BUFFERING bypasses the OS page
    # cache so reads hit the device, WRITE_THROUGH commits writes, and
    # SEQUENTIAL_SCAN hints "don't cache aggressively". Together with a
    # 4096-aligned read buffer (see _Win32RawDevice.read), this is the
    # recipe that lets the post-write verify read truth on the first pass.
    h = k.CreateFileW(
        path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING,
        FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH | FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    if h == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateFileW({path}) failed")
    _log.info("open_raw_device(%s) -> handle 0x%X", path, h)
    # FSCTL_ALLOW_EXTENDED_DASD_IO lets us write any sector of the raw
    # device. NOTE: we deliberately do NOT call IOCTL_DISK_DELETE_DRIVE_LAYOUT
    # / IOCTL_DISK_UPDATE_PROPERTIES here. Those wipe the partition table and
    # force Windows to re-scan — which makes the shell see the disk go RAW
    # and fire the "Format K:?" / "K:\\ is not accessible" pop-up. They are
    # also unnecessary: what authorises raw in-partition writes is the
    # FSCTL_LOCK_VOLUME that lock_and_dismount now HOLDS for the whole flash
    # (the Win32DiskImager model). While we own that lock the partition
    # manager permits writes inside the locked volume AND cannot re-mount it
    # mid-flash, so no pop-up and no ERROR_ACCESS_DENIED. (The earlier
    # "write at 8 MB succeeds without the lock" probe was a false negative —
    # it ran on a card with NO drive letter, where the volume was already
    # un-mounted; a card whose FAT32 Windows still recognises needs the held
    # lock.) The deferred-MBR write happens at offset 0 via the orchestrator.
    try:
        _ctl(h, FSCTL_ALLOW_EXTENDED_DASD_IO)
        _log.info("  FSCTL_ALLOW_EXTENDED_DASD_IO OK on %s", path)
    except OSError as exc:
        _log.info(
            "  FSCTL_ALLOW_EXTENDED_DASD_IO failed for %s (%s) — continuing",
            path, exc,
        )
    return h


# ── Mount-point re-attach (post-write, pre-customize) ─────────────────────


def _list_volumes() -> list[str]:
    """Enumerate Windows volume GUIDs via FindFirstVolumeW / FindNextVolumeW."""
    k = kernel32()
    buf = ctypes.create_unicode_buffer(260)
    h = k.FindFirstVolumeW(buf, len(buf))
    if h == INVALID_HANDLE_VALUE:
        return []
    volumes: list[str] = [buf.value]
    try:
        while k.FindNextVolumeW(h, buf, len(buf)):
            volumes.append(buf.value)
    finally:
        k.FindVolumeClose(h)
    return volumes


def _volume_has_letter(volume_guid: str) -> bool:
    """True iff Mount Manager has at least one drive-letter alias for the volume."""
    k = kernel32()
    buf = ctypes.create_unicode_buffer(1024)
    returned = wintypes.DWORD(0)
    ok = k.GetVolumePathNamesForVolumeNameW(
        volume_guid, buf, len(buf), ctypes.byref(returned),
    )
    if not ok:
        return False
    # Mount Manager returns a multistring: drive letters first (e.g. "I:\\"),
    # mount point folders next. We only care whether ANY single-letter root
    # alias exists.
    raw = buf[: returned.value]
    parts = [p for p in raw.split("\x00") if p]
    return any(len(p) == 3 and p[1] == ":" and p[2] == "\\" for p in parts)


def _volume_has_recognised_fs(volume_guid: str) -> bool:
    """True iff Windows can parse the filesystem at the volume root.

    Used as a readiness probe BEFORE attaching a drive letter to a
    just-discovered volume. After a raw write + IOCTL_DISK_DELETE_DRIVE_LAYOUT,
    Mount Manager often still has the OLD volume entry around (the one we
    overwrote) for a few seconds; the NEW volume Windows assigns to the
    freshly-written FAT32 appears asynchronously. Attaching K: to the
    stale entry produces the "Le volume ne contient pas de système de
    fichiers connu" pop-up and a customize step that immediately fails
    with FileNotFoundError(errno=2). Skipping volumes whose
    GetVolumeInformationW returns False lets us wait for the real,
    parseable volume to materialise.
    """
    k = kernel32()
    name_buf = ctypes.create_unicode_buffer(256)
    fs_buf = ctypes.create_unicode_buffer(256)
    serial = wintypes.DWORD(0)
    max_comp = wintypes.DWORD(0)
    flags = wintypes.DWORD(0)
    ok = k.GetVolumeInformationW(
        volume_guid,
        name_buf, len(name_buf),
        ctypes.byref(serial),
        ctypes.byref(max_comp),
        ctypes.byref(flags),
        fs_buf, len(fs_buf),
    )
    if not ok:
        return False
    # An empty filesystem name string means Windows mounted the volume
    # but couldn't identify the filesystem — treat as not-ready.
    return bool(fs_buf.value)


def _suppress_shell_error_dialogs_for_process() -> None:
    """Tell Windows not to render shell-level error message boxes.

    Sets ``SEM_FAILCRITICALERRORS`` (0x0001) — when our process triggers
    a critical I/O error on a removable device (CD ejected, USB unplugged,
    "you need to format the disk in drive X:?"), the system DOES NOT
    display the message box. ``GetLastError`` still returns the
    underlying status code so we can surface a clean English message in
    the UI ourselves. Inherited by child processes — combined with
    Mount-Manager state pre-cleanup in ``lock_and_dismount``, this is
    the closest user-mode equivalent of rpi-imager's userspace FAT32
    writer that never asks Windows to mount the freshly-written
    partition at all.
    """
    k = kernel32()
    SEM_FAILCRITICALERRORS = 0x0001
    SEM_NOOPENFILEERRORBOX = 0x8000  # also suppresses "file in use" dialogs
    try:
        # Preserve the existing flags so other process facets keep working.
        prev = k.GetErrorMode()
        k.SetErrorMode(prev | SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX)
        _log.info(
            "  SetErrorMode SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX OK "
            "(was 0x%04X)", prev,
        )
    except Exception as exc:  # noqa: BLE001
        _log.info(
            "  SetErrorMode failed (%s) — Windows pop-ups may still appear", exc,
        )


def _volume_disk_extents(volume_guid: str) -> list[int]:
    r"""Return list of PhysicalDrive numbers backing this volume.

    Uses ``IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS`` — returns a struct
    ``VOLUME_DISK_EXTENTS`` whose layout is:

        struct VOLUME_DISK_EXTENTS {
            DWORD NumberOfDiskExtents;
            DWORD _padding;          // alignment to 8-byte
            DISK_EXTENT Extents[1];  // variable-length array
        };
        struct DISK_EXTENT {
            DWORD DiskNumber;
            DWORD _padding;          // alignment to 8-byte
            LONGLONG StartingOffset;
            LONGLONG ExtentLength;
        };

    Returns the DiskNumber of each extent. Empty list on any failure
    (the caller treats this as "can't identify the backing drive" and
    refuses to attach a letter to the volume).
    """
    k = kernel32()
    path = volume_guid.rstrip("\\")  # CreateFileW dislikes trailing backslash here
    h = k.CreateFileW(
        path, 0,  # zero access — query-only, no read/write needed
        FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING, 0, None,
    )
    if h == INVALID_HANDLE_VALUE:
        return []
    try:
        out_buf = (ctypes.c_byte * 4096)()
        returned = wintypes.DWORD(0)
        ok = k.DeviceIoControl(
            h, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS,
            None, 0, out_buf, ctypes.sizeof(out_buf),
            ctypes.byref(returned), None,
        )
        if not ok:
            return []
        raw = bytes(out_buf)
        n = _struct.unpack_from("<I", raw, 0)[0]
        # First DISK_EXTENT starts at offset 8 (after NumberOfDiskExtents + padding)
        disks: list[int] = []
        for i in range(n):
            extent_off = 8 + i * 24  # each DISK_EXTENT is 24 bytes (4+4 pad+8+8)
            if extent_off + 4 > len(raw):
                break
            disks.append(_struct.unpack_from("<I", raw, extent_off)[0])
        return disks
    finally:
        k.CloseHandle(h)


def attach_letter_to_unmounted_volume(
    letter: str,
    physical_drive_id: int,
    timeout_s: float = 15.0,
) -> bool:
    r"""Assign ``letter`` to the letterless volume backed by ``physical_drive_id``.

    Post-write counterpart of ``_delete_mount_point``: after the raw flash
    completes (and we ran ``update_disk_properties``), Mount Manager
    discovers the new partition as a "letterless" volume. We assign our
    original drive letter back so ``DriveLetterBootPartition(letter)`` can
    write the AstromechOS bundle through normal Win32 file I/O.

    The ``physical_drive_id`` filter is **safety-critical**: a naive
    "first letterless volume" scan would happily attach the letter to a
    Windows Recovery NTFS partition or any other letterless volume on
    the system — the operator's letter would land on the wrong drive
    and the customize step's bundle would never reach the SD.

    Polls up to ``timeout_s`` seconds because Mount Manager registers
    the new volume asynchronously after the partition-table re-read.

    Returns True on success, False if no matching letterless volume
    showed up within the timeout (caller logs / treats as failure).
    """
    k = kernel32()
    mount_path = f"{letter}:\\"
    deadline = time.monotonic() + timeout_s
    seen_letterless: set[str] = set()
    while time.monotonic() < deadline:
        for vol in _list_volumes():
            if _volume_has_letter(vol):
                continue
            extents = _volume_disk_extents(vol)
            if physical_drive_id not in extents:
                if vol not in seen_letterless:
                    seen_letterless.add(vol)
                    _log.info(
                        "  skipping letterless volume %s (backed by disks %r, "
                        "not target %d)", vol, extents, physical_drive_id,
                    )
                continue
            # Right physical drive — but is Windows done parsing its
            # filesystem? After IOCTL_DISK_DELETE_DRIVE_LAYOUT the stale
            # pre-flash volume entry may linger for a few seconds before
            # Mount Manager replaces it with the new one. Attaching the
            # operator letter to the stale entry produces the "Le volume
            # ne contient pas de système de fichiers connu" pop-up and a
            # customize step that fails with FileNotFoundError(errno=2).
            if not _volume_has_recognised_fs(vol):
                _log.info(
                    "  skipping volume %s on disk %d — GetVolumeInformationW "
                    "reports no recognised FS yet (will retry)",
                    vol, physical_drive_id,
                )
                continue
            # Match — and the FS is parseable.
            ok = bool(k.SetVolumeMountPointW(mount_path, vol))
            if ok:
                _log.info(
                    "  SetVolumeMountPointW(%s, %s) OK (disk %d)",
                    mount_path, vol, physical_drive_id,
                )
                return True
            err = ctypes.get_last_error()
            _log.info(
                "  SetVolumeMountPointW(%s, %s) failed (Win32 err %d)",
                mount_path, vol, err,
            )
        time.sleep(0.5)
    _log.info(
        "  No letterless volume on disk %d to attach %s to after %.1f s",
        physical_drive_id, mount_path, timeout_s,
    )
    return False


def close_handle(h: int | None) -> None:
    """Idempotent, recycle-safe CloseHandle.

    No-ops on a ``None`` / ``INVALID_HANDLE_VALUE`` / ``0`` handle so a
    double-close can NEVER reach Win32. This matters for two reasons:

      1. Calling ``CloseHandle`` twice on the same value fails with
         ERROR_INVALID_HANDLE (errno 6) — the noisy double-close.
      2. Far worse: Windows recycles handle VALUES. Between the first and
         second close, an unrelated ``CreateFileW`` may have been handed the
         same numeric value; the second ``CloseHandle`` would then close a
         LIVE handle belonging to another object, so a later legitimate
         operation on it fails with ERROR_ACCESS_DENIED (errno 5) on a
         handle the caller still believes is valid.

    Owners (``_Win32RawDevice`` / ``_PlainRawDevice`` / the locked volume
    handles) null their stored handle after the first close so the value is
    never passed here twice, and this guard is the belt-and-suspenders.
    """
    if h is None or h == INVALID_HANDLE_VALUE or h == 0:
        return
    ok = kernel32().CloseHandle(h)
    if not ok:
        _log.warning("CloseHandle(0x%X) failed err=%s", h, ctypes.get_last_error())
    else:
        _log.debug("CloseHandle(0x%X) ok", h)


def update_disk_properties(h: int) -> None:
    """After writing partition table, force Windows to re-enumerate volumes."""
    _ctl(h, IOCTL_DISK_UPDATE_PROPERTIES)


def synchronize_cache(h: int) -> None:
    """Flush the device + USB-bridge firmware write cache.

    Issues SCSI SYNCHRONIZE_CACHE(10) via IOCTL_SCSI_PASS_THROUGH_DIRECT so
    a cheap USB-SATA/USB-SD bridge commits its internal write cache to the
    flash before we read it back. Falls back to FlushFileBuffers when the
    bridge rejects the passthrough (common on consumer adapters). Best-
    effort: logs and returns on any failure.
    """
    from astromechos_imager.platform._win32 import (  # noqa: PLC0415
        IOCTL_SCSI_PASS_THROUGH_DIRECT, SCSI_IOCTL_DATA_UNSPECIFIED,
        SCSIOP_SYNCHRONIZE_CACHE, SCSI_PASS_THROUGH_DIRECT_WITH_SENSE,
    )
    k = kernel32()
    pkt = SCSI_PASS_THROUGH_DIRECT_WITH_SENSE()
    pkt.sptd.Length = ctypes.sizeof(type(pkt.sptd))
    pkt.sptd.CdbLength = 10
    pkt.sptd.DataIn = SCSI_IOCTL_DATA_UNSPECIFIED
    pkt.sptd.DataTransferLength = 0
    pkt.sptd.TimeOutValue = 60
    pkt.sptd.SenseInfoLength = 32
    pkt.sptd.SenseInfoOffset = (
        SCSI_PASS_THROUGH_DIRECT_WITH_SENSE.Sense.offset
    )
    pkt.sptd.Cdb[0] = SCSIOP_SYNCHRONIZE_CACHE  # 0x35
    out = wintypes.DWORD(0)
    ok = k.DeviceIoControl(
        h, IOCTL_SCSI_PASS_THROUGH_DIRECT,
        ctypes.byref(pkt), ctypes.sizeof(pkt),
        ctypes.byref(pkt), ctypes.sizeof(pkt),
        ctypes.byref(out), None,
    )
    if ok:
        _log.info("  SCSI SYNCHRONIZE_CACHE OK")
        return
    err = ctypes.get_last_error()
    _log.info("  SCSI SYNCHRONIZE_CACHE not supported (err %d) — "
              "falling back to FlushFileBuffers", err)
    try:
        k.FlushFileBuffers(h)
    except Exception:
        pass


def eject_media(h: int) -> None:
    """Best-effort eject. Caller logs warning on failure."""
    _ctl(h, IOCTL_STORAGE_EJECT_MEDIA)


# ── _Win32RawDevice + helpers ──────────────────────────────────────────────

from astromechos_imager.core.platform_io import RawDevice  # noqa: E402 (Protocol, no runtime dep)


class _Win32RawDevice:
    """RawDevice adapter wrapping a kernel32 HANDLE.

    The sector_size is queried lazily on first write/read so unit tests that
    only construct the object don't pay the syscall.
    """

    def __init__(self, handle: int, size_bytes: int):
        self._h = handle
        self.size_bytes = size_bytes
        self._sector_size: int | None = None

    @property
    def sector_size(self) -> int:
        if self._sector_size is None:
            self._sector_size = _query_sector_size(self._h)
        return self._sector_size

    def _require_open(self) -> int:
        h = self._h
        if h is None:
            raise OSError(6, "operation on a closed raw device handle")
        return h

    def write(self, offset: int, data: bytes) -> int:
        h = self._require_open()
        _seek(h, offset)
        written = wintypes.DWORD(0)
        ok = kernel32().WriteFile(
            h, ctypes.c_char_p(data), len(data),
            ctypes.byref(written), None,
        )
        if not ok:
            err = ctypes.get_last_error()
            _log.error("WriteFile FAILED: handle=0x%X offset=%d len=%d err=%d",
                       h, offset, len(data), err)
            raise OSError(err, f"WriteFile failed at offset {offset}")
        return written.value

    def read(self, offset: int, length: int) -> bytes:
        h = self._require_open()
        _seek(h, offset)
        # NO_BUFFERING requires a sector/page-aligned destination buffer.
        # A misaligned buffer can return stale bridge-cached bytes right
        # after a multi-GB write (the deterministic verify_readback bug).
        # rpi-imager uses qMallocAligned(size, 4096) (downloadthread.cpp:1882);
        # over-allocate and read into the 4096-aligned interior.
        align = 4096
        backing = (ctypes.c_char * (length + align))()
        aligned = (ctypes.addressof(backing) + align - 1) & ~(align - 1)
        buf = (ctypes.c_char * length).from_address(aligned)
        got = wintypes.DWORD(0)
        ok = kernel32().ReadFile(h, buf, length, ctypes.byref(got), None)
        if not ok:
            err = ctypes.get_last_error()
            _log.error("ReadFile FAILED: handle=0x%X offset=%d len=%d err=%d",
                       h, offset, length, err)
            raise OSError(err, f"ReadFile failed at offset {offset}")
        return bytes(buf.raw[: got.value])

    def flush(self) -> None:
        h = self._h
        if h is None:
            return  # already closed — nothing to flush, never raise
        kernel32().FlushFileBuffers(h)

    def close(self) -> None:
        # Idempotent: swap-then-close so the handle value is passed to
        # close_handle exactly once. A second close() (e.g. an orchestrator
        # finally racing a GC finalizer) sees None and no-ops — no
        # ERROR_INVALID_HANDLE, no risk of closing a recycled live handle.
        h, self._h = self._h, None
        close_handle(h)


class _PlainRawDevice:
    r"""Raw \\.\PHYSICALDRIVEn opened WITHOUT FILE_FLAG_NO_BUFFERING.

    The streaming-write handle uses NO_BUFFERING | WRITE_THROUGH for speed,
    but NO_BUFFERING also demands page-aligned USER BUFFERS — which plain
    ctypes buffers are not guaranteed to be. The userspace FAT customize
    (RawFatBootPartition) does many small, arbitrary-offset read-modify-
    write operations whose buffers come from Python, so it needs a plain
    (cached) handle: sector-aligned OFFSET/LENGTH is still required for a
    physical-drive handle, but the user buffer alignment is not. The
    RawSectorFile layer guarantees the sector alignment.

    Opened with no DELETE_DRIVE_LAYOUT / DASD calls — by the time customize
    runs, the streaming handle already wiped the layout, and the FAT region
    at 8 MB is writable.
    """
    SECTOR = 512

    def __init__(self, physical_drive_id: int):
        path = f"\\\\.\\PHYSICALDRIVE{physical_drive_id}"
        h = kernel32().CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE, None,
            OPEN_EXISTING, 0, None,
        )
        if h == INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            raise OSError(err, f"CreateFileW({path}) [plain] failed")
        self._h = h

    def _require_open(self) -> int:
        h = self._h
        if h is None:
            raise OSError(6, "operation on a closed plain raw device handle")
        return h

    def read(self, offset: int, length: int) -> bytes:
        h = self._require_open()
        _seek(h, offset)
        buf = ctypes.create_string_buffer(length)
        got = wintypes.DWORD(0)
        ok = kernel32().ReadFile(h, buf, length, ctypes.byref(got), None)
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(err, f"ReadFile [plain] failed at offset {offset}")
        return bytes(buf.raw[: got.value])

    def write(self, offset: int, data: bytes) -> int:
        h = self._require_open()
        _seek(h, offset)
        written = wintypes.DWORD(0)
        ok = kernel32().WriteFile(
            h, ctypes.c_char_p(data), len(data),
            ctypes.byref(written), None,
        )
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(err, f"WriteFile [plain] failed at offset {offset}")
        return int(written.value)

    def flush(self) -> None:
        h = self._h
        if h is None:
            return  # already closed — nothing to flush, never raise
        kernel32().FlushFileBuffers(h)

    def close(self) -> None:
        # Idempotent: see _Win32RawDevice.close. The userspace-FAT customize
        # closes this via RawFatBootPartition.close, which pyfatfs's GC
        # finalizers can re-enter — so the swap-then-close guard is what
        # keeps that second pass from re-closing a recycled handle value.
        h, self._h = self._h, None
        close_handle(h)


def open_plain_raw_device(physical_drive_id: int) -> _PlainRawDevice:
    """Open a plain (cached) raw device handle for the userspace FAT step."""
    return _PlainRawDevice(physical_drive_id)


def _seek(h: int, offset: int) -> None:
    new_pos = ctypes.c_longlong(0)
    ok = kernel32().SetFilePointerEx(h, offset, ctypes.byref(new_pos), 0)  # FILE_BEGIN
    if not ok:
        err = ctypes.get_last_error()
        _log.error("SetFilePointerEx FAILED: handle=0x%X offset=%d err=%d",
                   h, offset, err)
        raise OSError(err, f"SetFilePointerEx({offset}) failed")


def _query_sector_size(h: int) -> int:
    out = DISK_GEOMETRY_EX()
    written = wintypes.DWORD(0)
    ok = kernel32().DeviceIoControl(
        h, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, None, 0,
        ctypes.byref(out), ctypes.sizeof(out),
        ctypes.byref(written), None,
    )
    if not ok:
        return 512  # safe default
    return int(out.BytesPerSector)


# ── WindowsPlatformIO facade ───────────────────────────────────────────────

class WindowsPlatformIO:
    def enumerate_removable_drives(self):
        return list(enumerate_removable_drives())

    def lock_and_dismount(self, letters, physical_drive_id=None):
        return lock_and_dismount(letters, physical_drive_id)

    def open_raw_device(self, physical_drive_id):
        h = open_raw_device(physical_drive_id)
        # Re-query size from WMI to avoid a second sector_size syscall during write loop
        size = 0
        for d in enumerate_removable_drives():
            if d.physical_drive_id == physical_drive_id:
                size = d.size_bytes
                break
        return _Win32RawDevice(h, size)

    def open_plain_raw_device(self, physical_drive_id):
        """Cached (non-NO_BUFFERING) handle for the userspace FAT customize."""
        return open_plain_raw_device(physical_drive_id)

    def close_handle(self, handle):
        close_handle(handle)

    def update_disk_properties(self, handle):
        update_disk_properties(handle)

    def sync_cache(self, handle):
        """Flush the USB-bridge firmware write cache (SCSI SYNCHRONIZE_CACHE)."""
        synchronize_cache(handle)

    def eject_media(self, handle):
        eject_media(handle)

    def attach_letter_to_unmounted_volume(
        self, letter: str, physical_drive_id: int, timeout_s: float = 15.0,
    ) -> bool:
        """Re-attach the original drive letter after the Bug #0 dismount dance.

        Safety: filters letterless volumes by physical drive id so we never
        attach the operator's letter to a Windows Recovery partition or any
        other letterless system volume.
        """
        return attach_letter_to_unmounted_volume(letter, physical_drive_id, timeout_s)
