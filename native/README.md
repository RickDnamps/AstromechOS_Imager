# Native flash core (`astro_flash.dll`) — Phase 0 only

> **OUTCOME: the C++ rewrite turned out to be UNNECESSARY.** Both the
> Windows pop-up AND the verify failure were fixed in **pure Python**.
> This DLL shipped only as the Phase-0 "shell-quiet" de-risk helper
> (`SetThreadErrorMode` + `SHChangeNotify`); it is wired in as harmless
> belt-and-suspenders but is NOT what fixed the bugs. The fuller Phase
> 1/2 C++ port described below was never needed and is kept only as a
> design record. See the next section for what actually fixed it.

Native C++ helper for the Windows flash path, driven from Python over a
C ABI (ctypes). Reference implementation studied: `rpi-imager-main/`
(gitignored).

## The two bugs and how they were ACTUALLY fixed (pure Python)

The Step 5 "Format K:?" / "K:\\ is not accessible" pop-up and the
deterministic post-write verify mismatch were chased for a long time and
blamed (wrongly) on a USB-bridge cache. The real causes:

1. **Pop-up** — `DriveLetterBootPartition` forced a Windows MOUNT of the
   freshly-written FAT32 to write the firstboot bundle. Fixed by
   `core/raw_fat_partition.RawFatBootPartition`: a userspace FAT writer
   that drives `pyfatfs` over a raw-device sector window
   (`core/raw_sector_io.RawSectorFile`) — **no mount, no drive letter,
   no Explorer**, exactly rpi-imager's `DeviceWrapper` model but in
   Python. The orchestrator also writes the deferred MBR LAST so Windows
   never even discovers a partition during the flash.

2. **Verify mismatch** — a producer/consumer race in
   `core/diskwriter.py`: on a slow target the end-of-stream sentinel
   discarded the last queued data chunk, leaving the device ~1 MB short
   and `bytes_written` undercounted, so verify hashed a 1-MB-short
   readback against the full-image hash. Fixed by a blocking sentinel
   put that never drops a chunk. (Nothing to do with C++ or the bridge.)

So `pyfatfs` + a sector-window file object replaced the "irreducibly
native" userspace FAT writer, and a one-line queue fix restored verify.

## Ownership split

| Concern | Side | Module |
|---|---|---|
| Drive enumeration (WMI) | Python | `platform/windows.py` (unchanged) |
| Image format detect + **decompression** (.gz/.xz/.zip → 1 MB chunks) | Python | `core/imagesource.py` (unchanged) |
| MBR partition parse (FAT32 start/len, ext4 start) | Python | `core/bootpartition.py` (unchanged) |
| Firstboot bundle **content** (the bytes of init.cfg, keys, …) | Python | `core/customization.py` (unchanged) |
| Orchestration, role state, UI | Python | `core/orchestrator.py`, `ui/*` |
| Raw device open + lock/dismount + **shell-quieting** | **C++** | `win_raw_device`, `win_shell_quiet` |
| Streaming write (deferred first block) + in-flight SHA-256 | **C++** | `stream_writer`, `sha256_cng` |
| Verify readback + SHA-256 compare | **C++** | `verify_reader` |
| **Userspace FAT32** file read/write (no mount) | **C++** | `fat_partition`, `device_wrapper` |
| SCSI SYNCHRONIZE_CACHE (cheap-USB-bridge flush) | **C++** | `win_raw_device` |

## File tree

```
native/
  README.md                         ← this file
  build.ps1                         ← one-shot cl.exe build → vendor/astro_flash.dll
  astro_flash/
    include/
      astro_flash.h                 ← THE C ABI (extern "C") — only surface ctypes sees
    src/
      astro_flash.cpp               ← C ABI impl: opaque AstroDevice, arg marshalling,
                                       AstroStatus population (English-only messages)
      win_raw_device.{h,cpp}        ← CreateFileW(NO_BUFFERING|WRITE_THROUGH), overlapped
                                       WriteFile/ReadFile w/ retry, FSCTL_ALLOW_EXTENDED_DASD_IO,
                                       IOCTL_DISK_DELETE_DRIVE_LAYOUT, SCSI SYNCHRONIZE_CACHE
                                       (port of file_operations_windows.cpp:259-1000)
      win_shell_quiet.{h,cpp}       ← SetThreadErrorMode, per-letter lock+dismount+unlock,
                                       DeleteVolumeMountPointW, SHChangeNotify(MEDIA/DRIVE REMOVED)
                                       (port of diskpart_util.cpp:33-184 + platformquirks:215-225)
      stream_writer.{h,cpp}         ← deferred-first-block consumer + rolling throughput +
                                       progress callback (port of downloadthread write loop)
      verify_reader.{h,cpp}         ← readback loop, hash-injects deferred first block
                                       (port of downloadthread::_verify, :1873-1960)
      device_wrapper.{h,cpp}        ← block-cache pread/pwrite over the raw handle, sync()
                                       (port of devicewrapper.cpp, 209 L)
      fat_partition.{h,cpp}         ← userspace FAT16/32 reader+writer: cluster chains, FAT
                                       table, LFN dir entries, FSInfo (port of
                                       devicewrapperfatpartition.cpp, 1432 L — the big one)
      sha256_cng.{h,cpp}            ← BCrypt CNG SHA-256, hardware-accelerated
                                       (port of acceleratedcryptographichash_cng.cpp, 195 L)
  test/
    test_astro_flash.cpp            ← native gtest-free smoke harness (writes a fixture .img
                                       file, not a device — CI-safe)
```

## Python integration (drop-in, zero orchestrator churn)

New module `astromechos_imager/core/native_diskwriter.py` ctypes-wraps the
DLL and exposes the **same** symbols the orchestrator already imports:

```python
class NativeDiskWriter:                 # same ctor + .run() as core.diskwriter.DiskWriter
    def __init__(self, source, raw_device, on_progress=None, cancel_event=None): ...
    def run(self) -> DiskWriteResult: ...

def native_verify_readback(dev, expected_sha256, length, on_progress=None,
                           cancel_event=None, first_block=None) -> None: ...

class NativeFatBootPartition:           # satisfies core.platform_io.BootPartition Protocol
    def __init__(self, physical_drive_id, part_start, part_len): ...
    def write_bytes(self, path, data): ...
    def read_bytes(self, path): ...
    def mkdir(self, path): ...
    def exists(self, path) -> bool: ...
    def close(self): ...
```

`orchestrator.FlashJob` gets one factory switch (`use_native_core: bool`,
default True on Windows when the DLL is present, else fall back to the
current pure-Python path). Because `NativeFatBootPartition` satisfies the
existing `BootPartition` Protocol, **`FirstbootBundle.write_to` is
unchanged** — it just writes through the native FAT driver instead of a
drive letter. The `_assert_bp_targets_our_drive` safety check and the
`attach_letter_to_unmounted_volume` dance become **dead code on the native
path** (we write through the raw handle to a known physical drive — can't
leak to C: by construction). They stay as the pure-Python fallback's guard.

ctypes boundary detail: progress callbacks use `CFUNCTYPE(c_int, c_void_p,
c_int, c_uint64, c_uint64, c_double)`; the Python wrapper keeps a ref to
the callback object for the call's lifetime (GC-safety) and translates
`AstroProgressCb` → the existing `DiskWriterProgress` dataclass so the
FlashViewModel signals are unchanged.

## Build

MSVC 14.50 (VS BuildTools 18) is installed:
`C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC\14.50.35717`.
Python is 3.12.7 x64 (MSC v.1941) — same toolchain family, ABI-safe.

`build.ps1` invokes `cl.exe` via `vcvars64.bat`, no CMake required:

```
cl /LD /O2 /std:c++17 /DASTRO_FLASH_BUILD
   /I astro_flash\include
   astro_flash\src\*.cpp
   /link bcrypt.lib shell32.lib ole32.lib
   /OUT:..\vendor\astro_flash.dll
```

The DLL drops into `vendor/` alongside debugfs.exe and is picked up by the
existing `core/vendored_binaries.py` resolver (dev + frozen). PyInstaller
ships it via the same `vendor/` collection rule.

## Phased plan

**Phase 0 — de-risk the pop-up (½ day).** Build a *minimal* DLL exporting
only `astro_lock_and_quiet` (SetThreadErrorMode + DeleteVolumeMountPoint +
**SHChangeNotify**). Call it from the CURRENT Python flash path, before
the raw write, from the worker thread. If the "Format K:?" pop-up stops
firing, the userspace-FAT port is *optional polish*; if it still fires,
the FAT port is *mandatory*. Either way we learn the truth for ~80 lines
of C++ instead of 1600. **← propose we start here.**

**Phase 1 — raw write + verify in C++ (1–2 days).** `win_raw_device` +
`stream_writer` + `verify_reader` + `sha256_cng`. Python keeps
decompressing and pushes chunks. Restores `skip_verify=False` (the verify
runs through the quiet handle). Replaces `diskwriter.py` on the native path.

**Phase 2 — userspace FAT32 customize (2–3 days).** Port
`device_wrapper` + `fat_partition`. `NativeFatBootPartition` replaces
`DriveLetterBootPartition`. Kills the mount entirely. Removes the
letter-reattach dance from the hot path.

**Phase 3 — wire + harden (1 day).** Orchestrator factory switch,
`vendored_binaries` resolver entry, PyInstaller rule, native smoke test,
full E2E with `skip_verify=False` on real hardware → the "TOUT VERT" we
couldn't reach in pure Python.

## What stays pure-Python (and why that's correct)

Decompression. Pi-OS images are gzip/xz; Python's `gzip`/`lzma` already
stream them correctly and the per-chunk ctypes hop is microseconds against
a 1 MB memcpy + disk write. Porting libarchive into the DLL would add a
heavy dependency for zero measurable gain. The native core's job is the
*device*, not the *codec*.
