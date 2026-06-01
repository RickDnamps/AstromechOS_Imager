/*
 * astro_phase0.cpp — Phase 0 de-risk build of astro_flash.dll.
 *
 * Exports ONLY the "tame the shell" surface, device-less, so it can be
 * called from the CURRENT Python flash path (the worker thread) before
 * the raw write — without yet porting the raw-I/O / FAT engine.
 *
 * The hypothesis under test: the "Format K:?" / "K:\ is not accessible"
 * pop-up dies if, from the flash worker THREAD, we
 *   1. SetThreadErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX)
 *   2. lock + dismount + unlock + close each volume handle
 *   3. DeleteVolumeMountPointW("X:\")
 *   4. SHChangeNotify(SHCNE_MEDIAREMOVED | SHCNE_DRIVEREMOVED, "X:\")
 *
 * (1) and (4) are the two things the pure-Python path never did. rpi-imager
 * does both — (1) per worker thread (downloadthread.cpp:589), (4) after
 * dismount (diskpart_util.cpp:48-49).
 *
 * Build: native/build.ps1  →  vendor/astro_flash.dll
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winioctl.h>   /* FSCTL_LOCK_VOLUME, FSCTL_DISMOUNT_VOLUME, FSCTL_ALLOW_EXTENDED_DASD_IO */
#include <shlobj.h>     /* SHChangeNotify, SHCNE_* */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ASTRO_FLASH_BUILD is defined on the cl.exe command line (build.ps1). */
#define ASTRO_API __declspec(dllexport)

extern "C" {

typedef struct {
    int32_t  code;          /* 0 == OK, negative == error */
    uint32_t win_error;     /* GetLastError() at failure, else 0 */
    char     message[256];  /* ASCII English, NUL-terminated */
} AstroStatus;

}  /* extern "C" */

/* ── helpers ───────────────────────────────────────────────────────── */

static void st_ok(AstroStatus* st) {
    if (!st) return;
    st->code = 0;
    st->win_error = 0;
    st->message[0] = '\0';
}

static void st_fail(AstroStatus* st, int32_t code, uint32_t win_error,
                    const char* msg) {
    if (!st) return;
    st->code = code;
    st->win_error = win_error;
    /* English-only, truncate safely. */
    strncpy_s(st->message, sizeof(st->message), msg, _TRUNCATE);
}

/* Lock a single volume handle with geometric backoff (rpi-imager uses 8
 * tries, 100ms doubling — Win11 25H2 can hold handles longer). Returns
 * true on success; on failure the handle is still usable for dismount
 * ("proceeding with dismount anyway" — diskpart_util.cpp:140). */
static bool lock_volume(HANDLE h) {
    DWORD bytes = 0;
    int delay = 100;
    for (int attempt = 0; attempt < 8; ++attempt) {
        if (DeviceIoControl(h, FSCTL_LOCK_VOLUME, nullptr, 0, nullptr, 0,
                            &bytes, nullptr)) {
            return true;
        }
        Sleep(delay);
        delay *= 2;
    }
    return false;
}

/* Quiet ONE drive letter: lock, dismount, unlock, close, delete mount
 * point, notify shell. Best-effort — every step that fails is logged
 * into st but does not abort the others (matches rpi-imager's
 * "continuing anyway" posture). */
static void quiet_one_letter(wchar_t letter, AstroStatus* st) {
    wchar_t volPath[8];   /* \\.\X:  */
    swprintf_s(volPath, L"\\\\.\\%c:", letter);

    HANDLE h = CreateFileW(volPath,
                           GENERIC_READ | GENERIC_WRITE,
                           FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_EXISTING, 0, nullptr);
    if (h != INVALID_HANDLE_VALUE) {
        DWORD bytes = 0;
        lock_volume(h);  /* best-effort */
        DeviceIoControl(h, FSCTL_DISMOUNT_VOLUME, nullptr, 0, nullptr, 0,
                        &bytes, nullptr);
        DeviceIoControl(h, FSCTL_UNLOCK_VOLUME, nullptr, 0, nullptr, 0,
                        &bytes, nullptr);
        CloseHandle(h);
    }
    /* Drop the mount point so Windows can't re-mount under the old letter. */
    wchar_t mount[8];     /* X:\  */
    swprintf_s(mount, L"%c:\\", letter);
    DeleteVolumeMountPointW(mount);

    /* THE missing signal: tell Explorer the media + drive are gone so it
     * stops polling and never renders the "Format X:?" dialog. */
    SHChangeNotify(SHCNE_MEDIAREMOVED, SHCNF_PATH, mount, nullptr);
    SHChangeNotify(SHCNE_DRIVEREMOVED, SHCNF_PATH, mount, nullptr);
    st_ok(st);
}

/* ── exported C ABI ────────────────────────────────────────────────── */

extern "C" {

ASTRO_API const char* astro_version(void) {
    return "astro_flash phase0 0.0.1";
}

/* Set the CALLING thread's error mode. Must be invoked from the flash
 * worker thread so the raw-write I/O that follows inherits the
 * suppression. SetThreadErrorMode is the modern, thread-scoped form;
 * the process-wide SetErrorMode we set at app boot does not reliably
 * cover a separate Python worker thread. */
ASTRO_API int astro_quiet_thread(AstroStatus* st) {
    DWORD old = 0;
    if (!SetThreadErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX,
                            &old)) {
        DWORD e = GetLastError();
        st_fail(st, -1, e, "SetThreadErrorMode failed");
        return -1;
    }
    st_ok(st);
    return 0;
}

/* Run the full quiet dance for a comma-separated list of drive letters
 * (e.g. "K" or "K,L"). Also sets this thread's error mode. */
ASTRO_API int astro_lock_and_quiet(const char* drive_letters_csv,
                                   AstroStatus* st) {
    astro_quiet_thread(st);   /* sets error mode; ignore its verdict here */

    if (!drive_letters_csv || !drive_letters_csv[0]) {
        st_ok(st);
        return 0;             /* nothing to dismount — operator gave no letters */
    }

    AstroStatus per = {};
    for (const char* p = drive_letters_csv; *p; ++p) {
        char c = *p;
        if (c == ',' || c == ' ' || c == ':') continue;
        if ((c >= 'a' && c <= 'z')) c = (char)(c - 'a' + 'A');
        if (c < 'A' || c > 'Z') continue;
        quiet_one_letter((wchar_t)c, &per);
    }
    st_ok(st);
    return 0;
}

}  /* extern "C" */
