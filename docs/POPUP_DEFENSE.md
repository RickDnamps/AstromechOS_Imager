# The anti-"Format this disk?" defense stack

Windows pops *"You need to format the disk in drive X: before you can use
it"* whenever a **drive letter** lands on a volume whose filesystem it
cannot parse (RAW). During a flash, the target card is RAW *by design* for
minutes at a time — so the entire defense reduces to one invariant:

> **No drive letter may ever exist on the target disk while it is RAW.**

A healthy flashed Pi card never pops: Windows mounts the FAT32 `bootfs`
and silently ignores the ext4 rootfs (no letter ever lands on it). The
dialog is exclusively a flash-time pathology.

## The stack (v0.2.0 → v0.2.2, field-validated 2026-06-12)

| # | Defense | Where | Kills |
|---|---------|-------|-------|
| 1 | Automount disabled for the whole session (`mountvol /N`, crash marker in `%ProgramData%`, restored at quit / next-launch repair) | `platform/session_guard.py`, armed on a background thread at launch | Letters on *newly arriving* volumes |
| 2 | Scan-time letter strip of every non-suspect candidate disk (at bring-up, on list change, after arming completes) | `ui/app.py` `_strip_candidate_letters` | Letters that existed before launch, or that a **sticky `MountedDevices` binding** re-assigned at insertion despite automount-off |
| 3 | Active-wait unmount gate — never open `\\.\PhysicalDrive` while Windows still holds a letter | `core/orchestrator.py` `_wait_for_unmount` | The freshly-inserted card still held by Explorer/AutoPlay |
| 4 | **MBR scrub** — zero the first ≥4096 bytes right after `open_raw_device` | orchestrator, `PHASE mbr-scrub` | Field log #1 (2026-06-12): `IOCTL_DISK_DELETE_DRIVE_LAYOUT` only clears the *in-memory* layout; a mid-write shell re-query made disk.sys re-read the still-valid **old table from media**, resurrecting the old volumes mid-write |
| 5 | **Sticky-binding purge** (`mountvol /R`) right after the target's volumes are torn down | `platform/windows.py` `purge_stale_mount_points` | Field log #2 (2026-06-12): even with a blank sector 0, REMOVABLE media exposes a whole-disk "superfloppy" RAW volume on re-enumeration — and a sticky binding letters it anyway. With the bindings purged + automount off, **no letter can attach, period** |
| 6 | **Mid-flash letter watchdog** — COM-free poll of `letters_on_disk(target)` every 250 ms for the whole device-open window; strips and WARN-logs anything that appears | orchestrator, `letter-watchdog` thread | Whatever mechanism we have not met yet (the WARNING is the forensic trail) |
| 7 | Deferred-MBR-last write — the partition table appears on disk only after verify + customize | `core/diskwriter.py` | Auto-mount of half-written partitions |
| 8 | Native shell-quiet (`astro_flash.dll`: `SetThreadErrorMode` + `SHChangeNotify`) | `platform/native_shell_quiet.py` | Explorer's stale drive icons + hard-error dialogs |
| 9 | End-of-flash: eject, else `make_card_visible` attaches a letter **only** to the recognised-FS (FAT32 boot) volume | orchestrator + `attach_letter_to_unmounted_volume` | The "captive reader" (letterless card invisible until reinsertion) without ever lettering the ext4 |

## Windows facts that cost us field time

- `DeleteVolumeMountPointW` signals failure with a **FALSE return, not an
  exception** — a `contextlib.suppress` wrapper sees nothing. The strip
  races AutoPlay ~3 s after insertion; failures are now checked, retried
  3×, and WARN-logged (`force_unmount_letter`).
- Sticky `HKLM\SYSTEM\MountedDevices` bindings assign letters on volume
  **arrival** regardless of `mountvol /N`. They are created any time a
  card is inserted while automount is on (e.g. between app sessions).
- Direct registry edits of `MountedDevices` are **forbidden** here: a
  past experiment re-triggered the dialog on both cards. `mountvol /R`
  is the OS-sanctioned cleanup and only touches *absent* volumes.
- A pre-zero of sector 0 while the card still holds a letter makes
  things WORSE (RAW + lettered = instant dialog, field log 2026-06-10).
  The scrub is only safe because defenses 2–3 guarantee zero letters
  first. Both field logs are pinned in
  `tests/integration/test_flashjob_customize.py::test_flash_scrubs_sector0_before_stream`.

## Operator notes

- Re-flash **both cards of a pair in one wizard session**: the bootstrap
  hotspot SSID is minted per session and shared across the cycles (the
  ed25519 keypair is persisted across sessions; the hotspot SSID is not).
- If the dialog ever appears anyway: **never click Format** — the flash
  is unaffected (verify-readback proves the content); report the session
  log (`%APPDATA%\AstromechOS Imager\logs\flash-*.log`), which will
  contain the watchdog's `mid-flash watchdog: letter X appeared` line.
