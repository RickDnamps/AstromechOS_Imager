/*
 * astro_flash.h — C ABI for the AstromechOS Imager native flash core.
 *
 * This header is the ONE AND ONLY surface that the Python side (ctypes,
 * astromechos_imager/core/native_diskwriter.py) links against. It is a
 * pure C ABI — no C++ types cross the boundary — so the DLL is decoupled
 * from the Python version and bundles into PyInstaller as a plain
 * vendor/astro_flash.dll (same pattern as vendor/debugfs.exe).
 *
 * Design split (see native/README.md):
 *   Python owns : drive enumeration (WMI), image format detection +
 *                 streaming DECOMPRESSION (imagesource.py), MBR partition
 *                 parsing (find_first_fat32_partition), firstboot bundle
 *                 CONTENT generation (customization.py), orchestration, UI.
 *   C++   owns  : raw Win32 device I/O, in-flight SHA-256 (BCrypt CNG),
 *                 the deferred-first-block streaming write, verify readback,
 *                 the userspace FAT32 writer (NEVER mounts → no Explorer
 *                 pop-up), and the "tame the shell" layer (SetThreadErrorMode
 *                 + SHChangeNotify + DeleteVolumeMountPoint + DELETE_DRIVE_LAYOUT).
 *
 * Threading contract: every astro_* call for a given AstroDevice MUST come
 * from the SAME thread (the flash worker thread). astro_lock_and_quiet()
 * sets that thread's error mode; subsequent raw I/O on the handle inherits
 * the quiet behaviour. Call astro_open/lock_and_quiet/write*/verify/fat*
 * /close all from one thread.
 *
 * String convention: all char* IN are UTF-8; all char* OUT (incl.
 * AstroStatus.message) are ASCII-only English, NUL-terminated. No localized
 * OS strerror ever crosses the boundary (CLAUDE.md language rule).
 */
#ifndef ASTRO_FLASH_H
#define ASTRO_FLASH_H

#include <stdint.h>
#include <stddef.h>

#ifdef _WIN32
#  ifdef ASTRO_FLASH_BUILD
#    define ASTRO_API __declspec(dllexport)
#  else
#    define ASTRO_API __declspec(dllimport)
#  endif
#else
#  define ASTRO_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ── Status / error reporting ──────────────────────────────────────────
 * Every fallible call takes an AstroStatus* out-param. code == 0 means OK.
 * Negative codes are AstroErr values. win_error carries GetLastError() at
 * the failure point (0 when not applicable). message is a short English
 * diagnostic — safe to surface verbatim in the UI. */
typedef enum {
    ASTRO_OK                    =  0,
    ASTRO_ERR_OPEN              = -1,   /* CreateFileW on \\.\PHYSICALDRIVEn failed */
    ASTRO_ERR_LOCK             = -2,   /* FSCTL_LOCK_VOLUME failed after retries */
    ASTRO_ERR_WRITE             = -3,   /* WriteFile / short write */
    ASTRO_ERR_READ              = -4,   /* ReadFile during verify */
    ASTRO_ERR_SEEK              = -5,
    ASTRO_ERR_HASH_MISMATCH     = -6,   /* verify: computed != expected */
    ASTRO_ERR_CANCELLED         = -7,   /* progress cb returned 0 */
    ASTRO_ERR_FAT_PARSE         = -8,   /* userspace FAT: bad BPB / unsupported */
    ASTRO_ERR_FAT_NOSPACE       = -9,   /* userspace FAT: no free clusters */
    ASTRO_ERR_FAT_NOTFOUND      = -10,  /* userspace FAT: read of missing file */
    ASTRO_ERR_STATE             = -11,  /* API misuse (e.g. write_chunk before begin) */
    ASTRO_ERR_NOMEM             = -12,
    ASTRO_ERR_BADARG            = -13,
} AstroErr;

typedef struct {
    int32_t  code;          /* AstroErr; 0 == OK */
    uint32_t win_error;     /* GetLastError() at failure, else 0 */
    char     message[256];  /* ASCII English, NUL-terminated */
} AstroStatus;

/* Opaque device handle. */
typedef void* AstroDevice;

/* Progress callback. phase: 0 = write, 1 = verify. Return 1 to continue,
 * 0 to request cancellation (the call then returns ASTRO_ERR_CANCELLED).
 * Fired from the calling thread between I/O chunks — never re-entrant. */
typedef int (*AstroProgressCb)(void* user, int phase,
                               uint64_t bytes_done, uint64_t bytes_total,
                               double throughput_bps);

/* ── Lifecycle ─────────────────────────────────────────────────────── */

/* Open \\.\PHYSICALDRIVE<physical_drive_id> with
 * FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH. Returns NULL on
 * failure (st->code == ASTRO_ERR_OPEN). */
ASTRO_API AstroDevice astro_open(int physical_drive_id, AstroStatus* st);

/* Close the handle, free all internal state (block cache, hash ctx). */
ASTRO_API void astro_close(AstroDevice dev);

/* ── Tame the OS (call once, from the worker thread, after astro_open) ──
 * For each drive letter in drive_letters_csv (e.g. "K" or "K,L"):
 *   1. open \\.\X:, FSCTL_LOCK_VOLUME (8x geometric backoff), FSCTL_DISMOUNT_VOLUME,
 *      FSCTL_UNLOCK_VOLUME, CloseHandle.
 *   2. DeleteVolumeMountPointW("X:\\").
 *   3. SHChangeNotify(SHCNE_MEDIAREMOVED | SHCNE_DRIVEREMOVED, "X:\\").
 * Then on the raw device handle:
 *   4. SetThreadErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX).
 *   5. FSCTL_ALLOW_EXTENDED_DASD_IO.
 *   6. IOCTL_DISK_DELETE_DRIVE_LAYOUT + IOCTL_DISK_UPDATE_PROPERTIES.
 * This is the combined defence that keeps Explorer silent for the whole
 * write+verify+customize window. */
ASTRO_API int astro_lock_and_quiet(AstroDevice dev,
                                   const char* drive_letters_csv,
                                   AstroStatus* st);

/* ── Streaming write (Python pushes decompressed 1 MB chunks) ──────────
 * The first chunk is BUFFERED (deferred first block) — it carries the
 * MBR and is NOT written to the device until astro_write_first_block().
 * All chunks (incl. the first) feed the in-flight SHA-256. */
ASTRO_API int astro_write_begin(AstroDevice dev,
                                uint64_t uncompressed_total_or_0,
                                AstroStatus* st);
ASTRO_API int astro_write_chunk(AstroDevice dev,
                                const uint8_t* data, size_t len,
                                AstroStatus* st);
/* Finalize: flushes the device, returns the hex SHA-256 of the full
 * source stream (incl. the deferred first block) and total bytes. */
ASTRO_API int astro_write_end(AstroDevice dev,
                              char out_sha256_hex[65],
                              uint64_t* out_bytes_written,
                              AstroStatus* st);

/* ── Verify (BCrypt CNG SHA-256, reads through the still-quiet handle) ──
 * Hash-injects the deferred first block, then reads [first_block_len,
 * length) from the device and compares to expected_sha256_hex. */
ASTRO_API int astro_verify(AstroDevice dev,
                           const char* expected_sha256_hex,
                           uint64_t length,
                           AstroProgressCb cb, void* user,
                           AstroStatus* st);

/* Commit the deferred MBR to offset 0. Call AFTER astro_verify succeeds,
 * BEFORE astro_fat_open — restores the partition table so the FAT writer
 * (and the eventual Pi boot) sees a valid layout. */
ASTRO_API int astro_write_first_block(AstroDevice dev, AstroStatus* st);

/* Flush the device + USB-bridge firmware cache. Tries SCSI
 * SYNCHRONIZE_CACHE (10h) via IOCTL_SCSI_PASS_THROUGH_DIRECT; falls back
 * to FlushFileBuffers on bridges that reject passthrough. */
ASTRO_API int astro_sync_cache(AstroDevice dev, AstroStatus* st);

/* ── Userspace FAT32 customize (NEVER mounts the partition) ────────────
 * part_start / part_len come from the Python MBR parse
 * (find_first_fat32_partition). All file paths are forward-slash,
 * partition-root-relative ("/astromech_secrets/init_config.json").
 * Reads/writes go through the raw handle's block cache — Windows never
 * mounts the volume, so no "Format K:?" pop-up can fire. */
ASTRO_API int astro_fat_open(AstroDevice dev,
                             uint64_t part_start, uint64_t part_len,
                             AstroStatus* st);
ASTRO_API int astro_fat_write_file(AstroDevice dev, const char* path_utf8,
                                   const uint8_t* data, size_t len,
                                   AstroStatus* st);
/* out may be NULL to query length only (out_len set, returns OK). */
ASTRO_API int astro_fat_read_file(AstroDevice dev, const char* path_utf8,
                                  uint8_t* out, size_t cap, size_t* out_len,
                                  AstroStatus* st);
ASTRO_API int astro_fat_exists(AstroDevice dev, const char* path_utf8,
                               int* out_exists, AstroStatus* st);
ASTRO_API int astro_fat_mkdir(AstroDevice dev, const char* path_utf8,
                              AstroStatus* st);
/* Flush the FAT block cache + first-block to the device. */
ASTRO_API int astro_fat_sync(AstroDevice dev, AstroStatus* st);

/* Optional: register a progress callback used by astro_write_chunk so
 * Python doesn't have to thread one through every chunk call. */
ASTRO_API void astro_set_progress_cb(AstroDevice dev,
                                     AstroProgressCb cb, void* user);

/* Library version, for the Python wrapper to sanity-check the bundled DLL. */
ASTRO_API const char* astro_version(void);

#ifdef __cplusplus
}  /* extern "C" */
#endif

#endif /* ASTRO_FLASH_H */
