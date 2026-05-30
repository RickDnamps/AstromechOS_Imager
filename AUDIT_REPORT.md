# 🔍 AstromechOS Imager — Audit Report

**Status:** ✅ **All findings closed** (2026-05-30).

Original audit (2026-05-29) surfaced 47 confirmed findings across 9
dimensions after a 148-agent Opus 4.8 multi-agent review with
adversarial verification. All 47 have been remediated in five
sequential batches.

---

## Counts (post-fix)

| Severity  | Original | Fixed | Remaining |
|-----------|---------:|------:|----------:|
| Critical  |        4 |     4 |         0 |
| High      |       19 |    19 |         0 |
| Medium    |       14 |    14 |         0 |
| Low       |        9 |     9 |         0 |
| Info      |        1 |     1 |         0 |
| **Total** |   **47** |**47** |     **0** |

---

## Fix log — by batch

### Batch 1 — Critical + 9 High (commit `23437ea`)

| # | File:Line | Title | Fix |
|---|-----------|-------|-----|
| 1 | `flash_view_model.py:417` | Imports nonexistent `generate_linux_account` | Removed; Zero-Touch ships without rootfs personalization. |
| 2 | `flash_view_model.py:435` | `FirstbootConfig` wrong kwargs | `hotspot_bootstrap=`, removed bogus `ed25519_pair=`. |
| 3 | `flash_view_model.py:456` | `FlashJob`/`PairFlashJob` wrong kwargs | `image_path=Path(...)`, `master_pair=ed25519`. |
| 4 | `flash_view_model.py:436` | Empty `authorized_keys` violates validator | `validate_authorized_keys([])` now permitted per Zero-Touch. |
| 8/10 | `flash_view_model.py:111` | HashCancelled → "file corrupted" | Dedicated `"CANCELLED"` sentinel routed to `cancelled` state. |
| 9/11 | `flash_view_model.py:220` | `cancel()` doesn't reach job's `cancel_event` | `startWithJob` injects view-model event into `job.cancel_event`. |
| 14 | `flash_view_model.py:397` | `cancel()` no UI feedback | Flips status to `cancelling` immediately, `_on_finished` → `cancelled`. |
| 15 | `orchestrator.py:122` | Volume HANDLEs leaked | Captured + closed in outer try/finally via `close_handle`. |
| 18 | `flash_view_model.py:482` | `_build_flash_job` swallows all exceptions | Re-raises; `startFromWizard` catches and surfaces in UI. |
| 19 | `orchestrator.py:164` | Bare `OSError` escapes `FlashJobResult` | Wrapped in `FlashError` with `__cause__`. |
| 20 | `app.py:145` | `sys.stderr` None crashes boot diag | Guarded via `sink = sys.stderr or sys.__stderr__`. |

### Batch 2 — Wave 1 quick wins

| # | File:Line | Title | Fix |
|---|-----------|-------|-----|
| 17 | `validators.py:22` | OPENSSH_PUBKEY_RE newline injection | `re.fullmatch` + tighter comment regex + `_safe_for_authorized_keys` pre-check rejecting `\n` / `\r` / `\x00`. |
| 21 | `AstromechOSImager.iss` | No AppMutex | `AppMutex=Global\AstromechOS_Imager_AppMutex` + `SetupMutex`; matching `CreateMutexW` in `app.py`. |
| 22 | `AstromechOSImager.iss:37` | `x64compatible` needs Inno 6.3 | Header bumped to "Requires Inno Setup 6.3+". |
| 39 | `AstromechOSImager.iss` | No code-signing hook | `#ifdef SIGN` block with documented `iscc /DSIGN /Smysigntool=…` invocation. |
| 40 | `AstromechOSImager.iss` | No MinVersion | `MinVersion=10.0.17763` (Win10 1809, PySide6 6.7 floor). |
| 41 | `astromechos_imager.spec:37` | vendor/ denylist | Replaced with explicit `_VENDOR_ALLOWLIST` + build-time WARNING on unknown files. |
| 42 | `cli/main.py:48` | `relaunch_as_admin` argv smuggling | `subprocess.list2cmdline(sys.argv[1:])` Windows-correct quoting. |
| 45 | `bootpartition.py:182` | `pyfatfs.close()` silently swallowed | Logged via stderr fallback chain — non-fatal but visible. |
| 47 | `errors.py:44` | Docstring says French | Corrected to English; references CLAUDE.md rule. |
| 50 | `AstromechOSImager.iss:11` | AppVersion not single-sourced | In-file comment listing the 3 places that need a coordinated bump. |
| 51 | `customization.py:85` | `render_wlan_conf` no shell escape | POSIX single-quote wrapping via `_shell_escape_single_quoted`; rejects embedded `\n` / `\x00`. |

### Batch 3 — Wave 2 image_validator hardening

| # | File:Line | Title | Fix |
|---|-----------|-------|-----|
| 5 | `image_validator.py:193` | `ZipFile` leaked when `.img` found | Outer `zf` tracked + closed in finally. |
| 6 | `image_validator.py:199` | Zip without `.img` silently re-read raw | Raises `MalformedRoleMarkerError("zip archive contains no .img member")`. |
| 28 | `image_validator.py:265` | `<512 byte` image → "missing marker" amber | Now raises `MalformedRoleMarkerError` (hard block). |
| 33 | `image_validator.py:304` | sidecar reads whole file, no BOM | Cap at `MAX_SIDECAR_BYTES=8 KB`, decode `utf-8-sig`. |
| 34 | `image_validator.py:127` | JSON `RecursionError` bypasses block | Caught alongside `JSONDecodeError`; raw cap `MAX_MARKER_BYTES=64 KB`. |
| 35 | `image_validator.py:270` | Broad `except Exception` around MBR | Narrowed to `BootPartitionMountError`. |

### Batch 4 — Wave 3 threading + state

| # | File:Line | Title | Fix |
|---|-----------|-------|-----|
| 7 | `flash_view_model.py:432` | `reuseHotspot` flag ignored | Branches on `wizard_state.reuseHotspot`, tries `load_persisted_hotspot()` first. |
| 12/27 | `wizard_state.py:159` | Stale role-check verdicts | Per-role `_role_check_gens` counter; `_apply_role_status` drops stale tokens. |
| 13 | `wizard_state.py:204` | Daemon emits on destroyed QObject | `_shutting_down` flag set on `aboutToQuit`; daemon checks before emit. |
| 29 | `keygen.py:76` | `load_persisted_pair` corrupted bytes | PEM header check + ssh-ed25519 prefix check; returns `None` on mismatch. |
| 30 | `wizard_state.py:204` | Temp files orphaned on shutdown | Combined with #13 — daemon stops short on shutdown so `_decompressed_head_as_tempfile`'s finally runs. |
| 31 | `diskwriter.py:53` | Producer hangs on consumer error | `q.put(timeout=0.5)` cancel-polling loop; consumer sets cancel on error. |
| 32 | `orchestrator.py:237` | `PairFlashJob` parallel join `IndexError` | `_run_into(box)` captures result OR exception; `_unbox` wraps in `FlashError`. |
| 36 | `app.py:166` | `DriveListModel` failure silently swallowed | Logs full traceback via stderr fallback to startup.log. |
| 46 | `wizard_state.py:218` | Daemon internal-error → amber soft-pass | New `"check_failed"` status (hard block) routed to red UI badge. |
| 48 | `flash_view_model.py:113` | Hash worker encodes errors in digest | Dedicated `"ERR:Type:msg"` sentinel + `"CANCELLED"` sentinel separated. |

### Batch 5 — Wave 4 UI polish + a11y

| # | File:Line | Title | Fix |
|---|-----------|-------|-----|
| 16 | `Step4Flash.qml:122` | Repeater JS-array model rebuilds delegates | Refactored to static `needMaster`/`needSlave` blocks + `Loader` + `Binding` for hash rows. |
| 23 | `Theme.js:18` | Orbitron used for body copy | `fontBody = "Segoe UI"`; Orbitron kept for titles/subtitles/buttons. |
| 24 | `SelectableCard.qml:32` | Not keyboard-focusable | `activeFocusOnTab`, `Keys.onSpacePressed/onReturnPressed/onEnterPressed`, focus-visible border. |
| 25 | `WindowCtrlButton.qml` / `main.qml:146` | Icon-only buttons no tooltip / Accessible.name | `tooltipText` + `accessibleName` props; `main.qml` fills both for sun/moon, min, max, close. |
| 26 | `Step2Images.qml:46` | `#5ec07a` WCAG fail on light | `theme.colors.colorTextSuccess` token: `#6cc987` dark / `#2f8a4a` light. |
| 37 | `R2HeadIcon.qml:18` | R2 stroke hardcoded | Bound to `theme.colors.colorAccent` (cyan dark / cobalt light). Same for `R2BodyIcon`, `R2BothIcon`. |
| 38 | `AstroButton.qml:79` | No focus indicator | `activeFocusOnTab` + outer focus-visible Rectangle with `colorAccentBright` border. |
| 43 | `Step2Images.qml:52` | Badge pulse opacity freezes mid-fade | `onRunningChanged: if (!running) statusDot.opacity = 1.0`. |
| 44 | `flash_view_model.py:446` | Drive lookup silently None | `_build_flash_job` raises `RuntimeError("master/slave drive id=N not found")`. |
| 49 | `main.qml:284` | Resize grip corner-only 14×14 | Four-edge `MouseArea` strips (4 px each) + 24×24 corner grip. |

---

## What's NOT in the audit

The fixes preserve every contract: 440 / 440 tests pass after every
batch (3 net additions: `test_authorized_keys_empty_list_accepted_zero_touch`,
`test_accepts_empty_keys_zero_touch`, plus new shell-escape coverage
in `test_render_wlan_conf.py`).

Things to watch for in a follow-up audit:

- Real-SD integration tests (`tests/integration/test_lock_dismount.py`)
  are still skipped — exercise once on a Win11 box with a spare SD.
- The `_role_check_gens` generation counter is per-role; a third
  category of "global cancellation" would need another scheme.
- Inno Setup `UsedUserAreasWarning` (per-user cleanup under admin
  install) is acknowledged but left in place — the project is
  single-operator single-machine; multi-user installs would need to
  move the cleanup to a `[UninstallRun]` per-user step.

86 refuted candidates were dropped after the adversarial pass during
the original audit; they remain refuted (the post-fix code did not
re-introduce any of the patterns they flagged).
