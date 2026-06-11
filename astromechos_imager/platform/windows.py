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
    r"""Dismount every volume on the target, then RELEASE — return ``[]``.

    This restores the proven baseline recipe (commit 67138da) after the
    held-lock experiment regressed real flashes into ERROR_ACCESS_DENIED.
    The write authorisation does NOT come from a held FSCTL_LOCK_VOLUME — it
    comes from (a) DISMOUNTING the volume so the shell drops it, (b)
    DeleteVolumeMountPointW removing the drive letter from Mount Manager, and
    (c) IOCTL_DISK_DELETE_DRIVE_LAYOUT in ``open_raw_device`` wiping the
    in-memory partition table so PARTMGR no longer polices in-partition
    writes. The orchestrator calls this BEFORE ``open_raw_device``.

    Per volume: FSCTL_LOCK_VOLUME (retries) → FSCTL_DISMOUNT_VOLUME →
    FSCTL_UNLOCK_VOLUME → CloseHandle. We do NOT keep the lock: holding it
    while the physical drive is opened/written denies the in-partition write
    on real hardware. The lock here is only the standard "flush + invalidate
    open handles" step before dismount.

    No pop-up: DeleteVolumeMountPointW removes the letter the shell would
    fire "Format K:?" against, the deferred-MBR design keeps the partition
    table off-disk for the whole write/verify/customize window, and
    native_shell_quiet fires SHChangeNotify(MEDIA/DRIVE REMOVED).

    Volume discovery: by VOLUME GUID when ``physical_drive_id`` is given
    (``_list_volumes`` covers lettered AND letterless volumes), else by the
    ``letters`` fallback. Returns ``[]`` — no handle for the caller to manage
    (API shape preserved for the PlatformIO Protocol + FlashJob cleanup).
    """
    open_paths: list[str] = []
    if physical_drive_id is not None:
        try:
            for vol in _list_volumes():           # \\?\Volume{guid}\
                if physical_drive_id in _volume_disk_extents(vol):
                    open_paths.append(vol.rstrip("\\"))
        except Exception as exc:  # noqa: BLE001
            _log.info("volume enumeration for dismount failed (%s) — "
                      "falling back to drive letters", exc)
    if not open_paths:
        for letter in letters:
            open_paths.append(f"\\\\.\\{letter}:")
    _log.info("lock_and_dismount: phys_id=%s letters=%s -> %d volume(s): %s",
              physical_drive_id, letters, len(open_paths), open_paths)

    seen: set[str] = set()
    for open_path in open_paths:
        if open_path in seen:
            continue
        seen.add(open_path)
        h = _open_volume_handle(open_path)
        if h == INVALID_HANDLE_VALUE:
            continue   # volume vanished / no media — skip
        last_err = None
        locked = False
        for _attempt in range(8):
            try:
                _ctl(h, FSCTL_LOCK_VOLUME)
                locked = True
                break
            except OSError as e:
                last_err = e
                time.sleep(0.25)
        if not locked:
            _log.info("  FSCTL_LOCK_VOLUME failed for %s (%s) — dismounting "
                      "anyway (best-effort)", open_path, last_err)
        try:
            _ctl(h, FSCTL_DISMOUNT_VOLUME)
        except OSError as e:
            _log.info("  FSCTL_DISMOUNT_VOLUME failed for %s (%s)", open_path, e)
        # Release the lock + close the handle — we do NOT hold it.
        try:
            _ctl(h, FSCTL_UNLOCK_VOLUME)
        except OSError:
            pass
        kernel32().CloseHandle(h)
        _log.info("  dismounted + released %s", open_path)

    # Remove the drive letter(s) from Mount Manager so the shell has no
    # letter to render "Format K:?" against (baseline pop-up suppression).
    #
    # Bug fix 2026-06-11 (field: K: stayed visible through the whole Master
    # flash): ``letters`` comes from the WMI scan and is STALE — the operator
    # inserts the card AFTER the drive list was captured (wizard Step 4), so
    # the live letter Windows just assigned is not in the list and was never
    # deleted. Re-enumerate the letters LIVE from Mount Manager for this
    # physical disk and merge them with the caller's list before deleting.
    live_letters: list[str] = []
    if physical_drive_id is not None:
        try:
            live_letters = letters_on_disk(physical_drive_id)
        except Exception as exc:  # noqa: BLE001
            _log.info("  live letter enumeration failed (%s) — using the "
                      "scan-time list only", exc)
    all_letters = tuple(dict.fromkeys([*letters, *live_letters]))
    if set(all_letters) - set(letters):
        _log.info("  stale scan list %s — live letters on disk %s: %s",
                  letters, physical_drive_id, live_letters)
    for letter in all_letters:
        try:
            _delete_mount_point(letter)
        except Exception as exc:  # noqa: BLE001
            _log.info("  _delete_mount_point(%s) failed (%s)", letter, exc)

    # Native shell-quiet: SHChangeNotify(MEDIAREMOVED | DRIVEREMOVED) so
    # Explorer stops polling the device and never renders the modal dialog.
    try:
        from astromechos_imager.platform import native_shell_quiet
        if native_shell_quiet.available() and all_letters:
            native_shell_quiet.lock_and_quiet(all_letters)
    except Exception as exc:  # noqa: BLE001
        _log.info("native shell-quiet unavailable (%s) — continuing", exc)

    # Mount-Manager + Volume Snapshot Service settle. Without it the next
    # CreateFileW on \\.\PHYSICALDRIVEn can land in a transitional state and
    # in-partition writes return ERROR_ACCESS_DENIED (matches rpi-imager's
    # QThread::msleep between volumes in diskpart_util.cpp).
    time.sleep(1.0)
    return []


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
    # FSCTL_ALLOW_EXTENDED_DASD_IO lets us address any sector of the raw
    # device.
    try:
        _ctl(h, FSCTL_ALLOW_EXTENDED_DASD_IO)
        _log.info("  FSCTL_ALLOW_EXTENDED_DASD_IO OK on %s", path)
    except OSError as exc:
        _log.info(
            "  FSCTL_ALLOW_EXTENDED_DASD_IO failed for %s (%s) — continuing",
            path, exc,
        )
    # IOCTL_DISK_DELETE_DRIVE_LAYOUT wipes the in-memory partition table so
    # PARTMGR no longer policies writes as "inside a recognised partition" —
    # this is what AUTHORISES the FAT32-offset write that otherwise returns
    # ERROR_ACCESS_DENIED (errno 5).
    #
    # We deliberately do NOT follow it with IOCTL_DISK_UPDATE_PROPERTIES.
    # That call FORCES Windows to re-enumerate the disk immediately; on a
    # card that still carried a clean, Windows-RECOGNISED FAT32 (e.g. a card
    # just flashed as Master and being re-flashed as Slave), the forced
    # re-scan makes the shell see the volume vanish → the "Format K:?" pop-up
    # fires. DELETE_DRIVE_LAYOUT alone authorises the write without provoking
    # the shell; the layout is updated lazily by Windows on its own, and the
    # deferred MBR (written LAST) means no recognised partition exists during
    # the whole write/verify/customize window. Best-effort: some bridges
    # reject the layout wipe, in which case we log and continue.
    try:
        _ctl(h, IOCTL_DISK_DELETE_DRIVE_LAYOUT)
        _log.info("  IOCTL_DISK_DELETE_DRIVE_LAYOUT OK on %s", path)
    except OSError as exc:
        _log.info("  IOCTL_DISK_DELETE_DRIVE_LAYOUT failed for %s (%s) — "
                  "continuing", path, exc)
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


def force_unmount_letter(letter: str) -> bool:
    r"""DEVICE-SAFE forced detach of a drive letter.

    Open ``\\.\X:``, ``FSCTL_DISMOUNT_VOLUME`` (a forced dismount invalidates
    any open handle — e.g. the Explorer window AutoPlay opened on a
    freshly-inserted card), then ``DeleteVolumeMountPointW`` to drop the letter.
    These are the EXACT same Win32 calls ``lock_and_dismount`` already uses
    without breaking the raw write — there is deliberately NO ``mountvol /D``
    (left the disk ERROR_NOT_READY) and NO ``MountedDevices`` registry edit
    (triggered a re-evaluation that popped the dialog on BOTH cards). Used by
    the orchestrator's active-wait gate to keep re-dismounting until Windows
    releases the letter. Best-effort.
    """
    letter = (letter or "").strip().rstrip("\\").rstrip(":")
    if len(letter) != 1 or not letter.isalpha():
        return False
    h = _open_volume_handle(f"\\\\.\\{letter}:")
    if h != INVALID_HANDLE_VALUE:
        locked = False
        for _ in range(4):
            try:
                _ctl(h, FSCTL_LOCK_VOLUME)
                locked = True
                break
            except OSError:
                time.sleep(0.15)
        try:
            _ctl(h, FSCTL_DISMOUNT_VOLUME)
        except OSError as exc:
            _log.info("  force_unmount_letter(%s): dismount failed (%s)", letter, exc)
        if locked:
            try:
                _ctl(h, FSCTL_UNLOCK_VOLUME)
            except OSError:
                pass
        kernel32().CloseHandle(h)
    try:
        kernel32().DeleteVolumeMountPointW(f"{letter}:\\")
    except Exception:  # noqa: BLE001
        pass
    return True


def letters_on_disk(physical_drive_id: int) -> list[str]:
    r"""COM-free: drive letters currently associated with ``physical_drive_id``.

    The orchestrator's active-wait gate polls this BETWEEN dismount attempts to
    decide whether Windows has finally released the card. It is COM-free
    (FindFirstVolume + IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS +
    GetVolumePathNamesForVolumeNameW, no WMI) so it works on the flash worker
    thread, which never initialises COM. Returns e.g. ``['K']`` or ``[]``.
    """
    k = kernel32()
    out: list[str] = []
    try:
        for vol in _list_volumes():           # \\?\Volume{guid}\
            if physical_drive_id not in _volume_disk_extents(vol):
                continue
            buf = ctypes.create_unicode_buffer(1024)
            returned = wintypes.DWORD(0)
            ok = k.GetVolumePathNamesForVolumeNameW(
                vol, buf, len(buf), ctypes.byref(returned),
            )
            if not ok:
                continue
            raw = buf[: returned.value]
            for p in raw.split("\x00"):
                if len(p) == 3 and p[1] == ":" and p[2] == "\\":
                    out.append(p[0])
    except Exception:  # noqa: BLE001
        pass
    return out


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


def restore_readable_exfat(physical_drive_id: int, timeout_s: float = 90.0) -> bool:
    r"""Best-effort: quick-format the target drive to a clean exFAT volume.

    Called after a CANCELLED or FAILED flash, where the card is left RAW
    (open_raw_device wiped the partition layout via
    IOCTL_DISK_DELETE_DRIVE_LAYOUT and the deferred MBR was never written).
    Windows then nags "Format K:?" and the operator thinks the card is
    bricked. A quick exFAT format gives them a clean, recognised drive of any
    size (exFAT has no 32 GB limit, unlike Windows' FAT32 formatter).

    Driven via ``diskpart /s <script>`` — ships with Windows, needs the admin
    rights the app already runs with, and opens its OWN device handles (so
    our raw handle must already be closed). STRICTLY scoped to
    ``physical_drive_id`` (``select disk N``), which is the very disk we just
    flashed — never another drive. Best-effort: returns False (logged) on any
    failure and NEVER raises, so it can run safely inside a cancel/cleanup
    path.
    """
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    script = "\r\n".join([
        f"select disk {physical_drive_id}",
        "clean",
        "create partition primary",
        # "NO NAME" = the neutral, factory-fresh label generic SD cards ship
        # with — so a cancelled flash leaves the card looking like a blank
        # card, not one branded by this tool.
        'format fs=exfat quick label="NO NAME"',
        # NOTE: no "assign". Windows auto-mounts the removable exFAT volume
        # and picks a free letter on its own — forcing one here just adds to
        # the drive-letter creep (each format = new volume GUID = Mount
        # Manager hands out the next free letter and remembers the old one).
        "exit",
        "",
    ])
    fd, path = tempfile.mkstemp(suffix="-astro-restore.txt", text=True)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(script)
        _log.info("restore_readable_exfat: diskpart quick exFAT on disk %d",
                  physical_drive_id)
        res = subprocess.run(
            ["diskpart", "/s", path],
            capture_output=True, text=True, timeout=timeout_s,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode == 0:
            _log.info("restore_readable_exfat: disk %d formatted exFAT OK",
                      physical_drive_id)
            return True
        _log.warning("restore_readable_exfat: diskpart rc=%d on disk %d\n%s",
                     res.returncode, physical_drive_id,
                     (res.stdout or "")[-500:])
        return False
    except Exception as exc:  # noqa: BLE001
        _log.warning("restore_readable_exfat: failed on disk %d (%s)",
                     physical_drive_id, exc)
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


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


def finalize_eject(physical_drive_id: int) -> bool:
    r"""Best-effort eject of \\.\PHYSICALDRIVEn on a FRESH minimal handle.

    Called AFTER the write handle is closed, so nothing pins the device — this
    tells Windows the media is gone and it drops the freshly-written volumes
    instead of prompting "Format?" for the unreadable ext4 rootfs partition.
    Many USB SD-card bridges don't support eject; returns False (logged) and
    never raises.
    """
    k = kernel32()
    path = f"\\\\.\\PHYSICALDRIVE{physical_drive_id}"
    h = k.CreateFileW(
        path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING, 0, None,
    )
    if h == INVALID_HANDLE_VALUE:
        _log.info("finalize_eject: open %s failed (err %d)", path, ctypes.get_last_error())
        return False
    try:
        _ctl(h, IOCTL_STORAGE_EJECT_MEDIA)
        _log.info("finalize_eject: %s media ejected", path)
        return True
    except OSError as exc:
        _log.info("finalize_eject: %s eject unsupported/failed (%s) — ignored", path, exc)
        return False
    finally:
        close_handle(h)


# ── Automount control (kill the post-flash "Format this disk?" pop-up) ──────
#
# After the deferred MBR is written, Windows re-enumerates the card, finds the
# FAT32 boot + unreadable ext4 rootfs partitions, auto-mounts them (assigns a
# drive letter) and pops "You need to format the disk" / "no recognized file
# system". The prompt REQUIRES a drive-letter assignment — so disabling
# automatic mounting of new volumes for the flash window kills it at the
# source, independently of whether the USB-SD bridge supports eject.
#
# `mountvol /N` disables, `mountvol /E` re-enables (system-wide, persisted in
# the mountmgr registry → needs the elevated process we already run as, plus a
# crash-safe marker so a killed run doesn't leave automount off forever).


def _automount_marker_path():
    from pathlib import Path
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    d = Path(base) / "AstromechOS_Imager"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d / "automount_disabled.marker"


def _run_mountvol(flag: str) -> bool:
    import subprocess
    try:
        subprocess.run(
            ["mountvol", flag],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception as exc:
        _log.info("mountvol %s failed (%s) — ignored", flag, exc)
        return False


def disable_automount() -> bool:
    """Disable Windows auto-mounting of new volumes for the flash window.

    Drops a crash-safe marker so a killed run is repaired on next launch (see
    ``restore_automount_if_crashed``). Returns True only when ``mountvol /N``
    succeeded, so the caller knows whether it must re-enable.
    """
    ok = _run_mountvol("/N")
    if ok:
        try:
            _automount_marker_path().write_text("disabled\n", encoding="ascii")
        except OSError:
            pass
        _log.info("automount disabled for the flash (mountvol /N)")
    return ok


def enable_automount() -> bool:
    """Re-enable Windows auto-mounting (``mountvol /E``) and clear the marker."""
    _run_mountvol("/E")
    try:
        _automount_marker_path().unlink(missing_ok=True)
    except OSError:
        pass
    _log.info("automount re-enabled (mountvol /E)")
    return True


def restore_automount_if_crashed() -> None:
    """If a previous run died with automount disabled (marker present), restore."""
    try:
        if _automount_marker_path().exists():
            _log.info("automount marker present — a previous run left automount "
                      "disabled; restoring")
            enable_automount()
    except OSError:
        pass


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


def _query_disk_size(h: int) -> int:
    """Total disk size in bytes, queried from an OPEN physical-drive handle.

    Uses IOCTL_DISK_GET_DRIVE_GEOMETRY_EX (DISK_GEOMETRY_EX.DiskSize). This
    deliberately avoids re-running the WMI enumeration: WMI is a COM call,
    and the flash runs on a Qt worker thread that has NOT initialised COM,
    so a WMI query there raises ``pywintypes.com_error`` (observed:
    -2147221020 'Incorrect syntax'). Reading the geometry from the handle we
    just opened needs no COM and works on any thread. Returns 0 on failure
    (callers treat size as advisory — the write is bounded by the source).
    """
    out = DISK_GEOMETRY_EX()
    written = wintypes.DWORD(0)
    ok = kernel32().DeviceIoControl(
        h, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, None, 0,
        ctypes.byref(out), ctypes.sizeof(out),
        ctypes.byref(written), None,
    )
    if not ok:
        return 0
    return int(out.DiskSize)


# ── WindowsPlatformIO facade ───────────────────────────────────────────────

class WindowsPlatformIO:
    def enumerate_removable_drives(self):
        return list(enumerate_removable_drives())

    def lock_and_dismount(self, letters, physical_drive_id=None):
        return lock_and_dismount(letters, physical_drive_id)

    def open_raw_device(self, physical_drive_id):
        h = open_raw_device(physical_drive_id)
        # Get the disk size from the handle we just opened (IOCTL, no COM).
        # The previous code re-ran the WMI enumeration here, but this method
        # runs on the Qt FLASH WORKER THREAD, which has not initialised COM —
        # so the WMI query raised pywintypes.com_error ('Incorrect syntax')
        # and aborted every real flash (invisible to direct-call test
        # harnesses that run on the COM-initialised main thread). IOCTL on
        # the open handle is thread-safe and COM-free.
        size = _query_disk_size(h)
        _log.info("open_raw_device: phys_id=%s handle=0x%X size=%d",
                  physical_drive_id, h, size)
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

    def restore_readable_exfat(self, physical_drive_id):
        """Quick-format the target to clean exFAT after a cancel/failure."""
        return restore_readable_exfat(physical_drive_id)

    def eject_media(self, handle):
        eject_media(handle)

    def finalize_eject(self, physical_drive_id):
        """Best-effort eject on a fresh handle after the write handle closed."""
        return finalize_eject(physical_drive_id)

    def letters_on_disk(self, physical_drive_id):
        """COM-free: drive letters currently associated with the target disk
        (active-wait gate polls this until Windows releases the card)."""
        return letters_on_disk(physical_drive_id)

    def force_unmount_letter(self, letter):
        """Device-safe forced detach of a drive letter (FSCTL dismount +
        DeleteVolumeMountPoint — no mountvol /D, no registry)."""
        return force_unmount_letter(letter)

    def disable_automount(self):
        """Disable Windows auto-mount for the flash (kills the Format pop-up)."""
        return disable_automount()

    def enable_automount(self):
        """Re-enable Windows auto-mount (call in the flash's finally)."""
        return enable_automount()

    def attach_letter_to_unmounted_volume(
        self, letter: str, physical_drive_id: int, timeout_s: float = 15.0,
    ) -> bool:
        """Re-attach the original drive letter after the Bug #0 dismount dance.

        Safety: filters letterless volumes by physical drive id so we never
        attach the operator's letter to a Windows Recovery partition or any
        other letterless system volume.
        """
        return attach_letter_to_unmounted_volume(letter, physical_drive_id, timeout_s)
