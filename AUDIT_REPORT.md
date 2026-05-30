# 🔍 AstromechOS Imager — Audit Report

## Executive summary

The audit surfaces a serious correctness gap concentrated in the UI flash path: `FlashViewModel._build_flash_job` is structurally broken across four independent ways (missing/nonexistent imports, wrong keyword arguments to `FirstbootConfig`, missing required `master_pair`/`image_path` on `FlashJob`/`PairFlashJob`, and an empty `authorized_keys` list that violates the validator). Each defect is silently swallowed by a broad `except Exception` that returns `None`, so the entire Zero-Touch wizard happy path fails invisibly — the operator clicks WRITE and nothing happens. Beyond that, the cancellation/concurrency story across `FlashViewModel` and `WizardState` is brittle (shared `threading.Event` racing between phases, daemon threads emitting on potentially-deleted QObjects, last-write-wins on rapid image re-selection, cancel surfacing as "file corrupted"), and the orchestrator leaks Windows volume lock handles and lets `OSError`/threaded exceptions escape the `FlashJobResult` contract. Strengths include a well-structured error taxonomy (`SDState`, typed `ImagerError` subclasses), a solid customization-layer self-validate, and a deliberate Zero-Touch design — but several layers contradict each other (validator vs. customization, marker policy hard-block vs. wizard soft-pass on internal errors), pointing at a recurring pattern: defensive `except Exception` blocks that mask real failures as benign states. QML polish, theming, and accessibility gaps (focus indicators, contrast, keyboard activation) are real but lower priority than the flash-path correctness work.

## Counts

| Severity  | Confirmed |
|-----------|-----------|
| Critical  | 4         |
| High      | 19        |
| Medium    | 14        |
| Low       | 9         |
| Info      | 1         |
| **Refuted by adversarial review** | 86 |

## Confirmed findings

### Critical

| # | File:Line | Dimension | Title | Fix |
|---|-----------|-----------|-------|-----|
| 1 | `astromechos_imager/ui/flash_view_model.py:417-419` | correctness | _build_flash_job imports nonexistent generate_linux_account | Implement `generate_linux_account()` in `core/keygen.py` returning a `LinuxAccount`, and stop swallowing import errors in `_build_flash_job`. |
| 2 | `astromechos_imager/ui/flash_view_model.py:435-443` | correctness | FirstbootConfig built with wrong keyword arguments | Drop `ed25519_pair=…`, rename `hotspot=…` to `hotspot_bootstrap=…`, and route the keypair through `master_pair=ed25519` on the job constructors. |
| 3 | `astromechos_imager/ui/flash_view_model.py:456-481` | correctness | PairFlashJob/FlashJob missing master_pair and using wrong argument names | Pass `master_pair=ed25519` to both jobs, pass `Path(wizard_state.*ImagePath)` to `image_path`/`master_image`/`slave_image`, and let the orchestrator call `open_image()` internally. |
| 4 | `astromechos_imager/ui/flash_view_model.py:436` | correctness | FirstbootConfig(authorized_keys=[]) violates validate_authorized_keys | Either relax `validate_authorized_keys` to permit empty under Zero-Touch, or pass the master's own public key, and document the chosen contract in CLAUDE.md. |

> **#1** _(flash_view_model.py:417-419)_ — `generate_linux_account` is not defined anywhere in the repo, so every UI flash hits an `ImportError` that the broad `except` swallows, silently aborting `startFromWizard`.
> **#2** _(flash_view_model.py:435-443)_ — `FirstbootConfig` has no `ed25519_pair` field and the hotspot field is `hotspot_bootstrap`; construction raises `TypeError`, the silent except returns `None`, and the wizard flash does nothing visible.
> **#3** _(flash_view_model.py:456-481)_ — Both jobs require `master_pair` and `FlashJob` expects `image_path: Path`, but the UI omits the key and feeds an opened `ImageSource` under the wrong kwarg name; every UI flash construction fails with `TypeError`.
> **#4** _(flash_view_model.py:436)_ — `validate_authorized_keys` raises on an empty list, so the Zero-Touch default (`authorized_keys=[]`) blocks `FirstbootConfig.__post_init__` once the upstream `TypeError`s are fixed, contradicting the customization layer that explicitly tolerates an empty master keys file.

### High

| # | File:Line | Dimension | Title | Fix |
|---|-----------|-----------|-------|-----|
| 5 | `astromechos_imager/core/image_validator.py:193-203` | correctness | zipfile.ZipFile leaked when an inner .img is found | Track `zf` alongside `src` and close both in the cleanup block. |
| 6 | `astromechos_imager/core/image_validator.py:199-201` | correctness | Zip without inner .img silently falls back to reading the zip as raw bytes | Raise `MalformedRoleMarkerError(path.name, "zip contains no .img member")` when no `.img` entry is found, instead of re-aliasing to the raw `.zip` stream. |
| 7 | `astromechos_imager/ui/flash_view_model.py:432, 425-432` | correctness | reuseHotspot flag ignored; persisted hotspot never reused | Branch on `wizard_state.reuseHotspot`: try `load_persisted_hotspot()` first, fall back to `generate_hotspot_bootstrap()` + `save_persisted_hotspot()` only on miss. |
| 8 | `astromechos_imager/ui/flash_view_model.py:98-120, 322-356` | correctness | HashCancelled is reported as a SHA-256 sidecar mismatch | Emit a dedicated sentinel (e.g. `digest="CANCELLED"`) on `HashCancelled` and handle it as a clean back-to-idle transition in `_on_hash_finished`. |
| 9 | `astromechos_imager/ui/flash_view_model.py:366-370` | correctness | cancel() during flash never reaches the FlashJob's own cancel_event | Construct one shared `threading.Event` in `__init__` and inject it into both `_HashWorker` and the `FlashJob`/`PairFlashJob` so cancel always reaches the active worker. |
| 10 | `astromechos_imager/ui/flash_view_model.py:110-115` | concurrency | Cancelled hash is reported to the UI as 'file corrupted' | Distinguish cancellation from sidecar mismatch via a sentinel/flag and treat it as a clean idle transition, not `_fail_verify`. |
| 11 | `astromechos_imager/ui/flash_view_model.py:220, 287` | concurrency | _cancel_event.clear() races with in-flight cancel between phases | Use a fresh per-phase `threading.Event` and gate `startWithJob` on `_cancel_event.is_set()` to avoid swallowing a pending cancel. |
| 12 | `astromechos_imager/ui/wizard_state.py:159-225` | concurrency | _kick_role_check has last-write-wins race when image path changes quickly | Add a per-role generation counter; capture it in the worker and drop late results whose token has been superseded. |
| 13 | `astromechos_imager/ui/wizard_state.py:204-225` | concurrency | Daemon role-check thread emits signal on WizardState that may be destroyed | Track in-flight threads, set a shutdown flag on `QApplication.aboutToQuit`/`QObject.destroyed`, and check it before `emit`. |
| 14 | `astromechos_imager/ui/flash_view_model.py:366-370` | concurrency | cancel() does not transition status; UI keeps showing 'verifying'/'flashing' | Set a `_cancelling` flag, switch `_status` to `"cancelling"`, emit `statusChanged` immediately, and transition to `"cancelled"` once the worker exits. |
| 15 | `astromechos_imager/core/orchestrator.py:119-165` | resources | Volume handles from lock_and_dismount() are leaked | Capture the returned handles and close every entry in an outer try/finally via `self.platform_io.close_handle(h)`. |
| 16 | `astromechos_imager/ui/qml/Step4Flash.qml:122-155, 206-282` | qml | Repeater driven by an inline JS array literal rebuilds delegates on every property change | Replace the JS-array model with stable `needMaster`/`needSlave`-gated `ColumnLayout` blocks binding directly to view-model properties (as the flash-progress panel already does). |
| 17 | `astromechos_imager/core/validators.py:22-27` | validation | OPENSSH_PUBKEY_RE accepts keys with embedded newlines, enabling authorized_keys injection | Use `re.fullmatch`, tighten the comment portion to `(?:[ \t]+\S.*)?$`, and pre-reject any key containing `\n`, `\r`, or `\x00`. |
| 18 | `astromechos_imager/ui/flash_view_model.py:482-485` | errors | _build_flash_job swallows every exception and returns None to the wizard | Keep the broad catch but set `_status="error"`, `_error_message=str(exc)`, and emit `errorMessageChanged` so the operator actually sees the failure. |
| 19 | `astromechos_imager/core/orchestrator.py:119-165` | errors | FlashJob.run only catches ImagerError, letting raw OSError/RuntimeError crash the worker thread | Broaden to `except Exception`, wrap unexpected errors in a generic `ImagerError` (or carry `error=e` on `FlashJobResult`), and guard `m_result`/`s_result` indexing in `PairFlashJob`. |
| 20 | `astromechos_imager/ui/app.py:22-30, 145-148` | build | Boot diagnostic writes to sys.stderr that can be None when log open fails | Gate the `[boot]` writes on `_LOG_FH is not None`, or reuse the `sink = sys.stderr or sys.__stderr__; if sink:` pattern already used by `_qt_message_handler`. |
| 21 | `installer/AstromechOSImager.iss:18-46` | build | Installer has no AppMutex — installer can run while app is flashing raw disks | Add `AppMutex=AstromechOS_Imager_AppMutex` and `SetupMutex=AstromechOS_Imager_Setup_{#AppVersion}` under `[Setup]` and create the matching named mutex in `app.py`. |
| 22 | `installer/AstromechOSImager.iss:37-38` | build | ArchitecturesAllowed=x64compatible requires Inno Setup 6.3+, docs say 6.2+ | Bump the documented minimum to Inno Setup 6.3+ in both the `.iss` header and BUILD_INSTRUCTIONS.md (preferred), or fall back to `x64`. |
| 23 | `astromechos_imager/ui/qml/Theme.js:18` | polish | Body copy renders in Orbitron — a display face never intended for paragraphs | Set `fontBody` to a humanist sans (e.g. Segoe UI / bundled Inter), reserve Orbitron for titles/subtitles, and bump body to ≥13 px. |
| 24 | `astromechos_imager/ui/qml/Step1Mode.qml:32-52` | polish | SelectableCard is mouse-only — no Tab focus, no Space/Enter activation | Add `activeFocusOnTab: true`, `Keys.onSpacePressed`/`onReturnPressed` emitting `clicked()`, and a focus-visible border on SelectableCard. |
| 25 | `astromechos_imager/ui/qml/main.qml:146-169` | polish | Icon-only window/theme buttons have no tooltips or accessible names | Add `ToolTip` + `Accessible.name` to WindowCtrlButton plus `Keys.onSpacePressed`/`Returned` and `activeFocusOnTab`. |
| 26 | `astromechos_imager/ui/qml/Step2Images.qml:46-72` | polish | Hardcoded green #5ec07a fails WCAG AA on white cards (light theme) | Move success colour into ThemeManager (e.g. `colorTextSuccess` = `#2f8a4a` light / `#6cc987` dark) and bind via `theme.colors.colorTextSuccess`. |

> **#5** _(image_validator.py:193-203)_ — The outer `ZipFile zf` is never closed in the inner-`.img` branch, leaking a file handle until garbage collection and risking warnings/inconsistency with the sibling branch.
> **#6** _(image_validator.py:199-201)_ — A zip with no `.img` member is silently re-read as raw bytes, producing a confusing `cannot parse MBR` error instead of the truthful diagnostic.
> **#7** _(flash_view_model.py:432, 425-432)_ — `generate_hotspot_bootstrap()` is called unconditionally despite the `reuseHotspot` toggle and the persistence helpers being shipped; partial re-flashes lose hotspot symmetry across master/slave.
> **#8** _(flash_view_model.py:98-120, 322-356)_ — Cancellation arrives as `digest=""` with `match=False`, which routes through `_fail_verify("SHA-256 mismatch … file looks corrupted")` — operators see a corruption error after they themselves clicked Cancel.
> **#9** _(flash_view_model.py:366-370)_ — `_cancel_event` is the view-model's event, not the job's; for a cancel arriving before `startWithJob`, the job's own event (the one DiskWriter consults) never sees the signal and the flash proceeds.
> **#10** _(flash_view_model.py:110-115)_ — Duplicate of #8 in concurrency framing: the `(digest="", match=False)` overload conflates user-initiated cancel with file corruption, eroding operator trust.
> **#11** _(flash_view_model.py:220, 287)_ — Both `_begin_verify_phase` and `startWithJob` unconditionally `clear()` the shared event; a cancel issued between the last successful hash and the flash start is silently discarded and the destructive write begins.
> **#12** _(wizard_state.py:159-225)_ — Each path change spawns a fresh daemon thread with no token; a slower verdict for image A can overwrite the correct verdict for image B, leading to misleading badges and a potentially mis-gated NEXT button.
> **#13** _(wizard_state.py:204-225)_ — Daemon role-check threads can outlive the `WizardState` QObject (especially under test teardown or app shutdown mid-validation), and emitting a Qt signal on a deleted QObject is undefined behaviour.
> **#14** _(flash_view_model.py:366-370)_ — `cancel()` only flips events, so the UI remains in `verifying`/`flashing` for seconds; operators keep clicking the button and may even race the verify→flash transition.
> **#15** _(orchestrator.py:119-165)_ — `lock_and_dismount` returns a list of kernel32 volume HANDLEs that the orchestrator discards; volumes stay locked until process exit, breaking "Flash another" and Explorer remount.
> **#16** _(Step4Flash.qml:122-155, 206-282)_ — Inline JS-array models with embedded bindings cause `Repeater` to rebuild delegates on every progress tick, killing the `Behavior on width` interpolation and wasting CPU during hashing.
> **#17** _(validators.py:22-27)_ — The pubkey regex's `\s+.+` and `re.match` (vs `fullmatch`) let `ssh-ed25519 AAA\nssh-rsa BACKDOOR` pass validation; a future "paste keys" path would write both entries to `authorized_keys`.
> **#18** _(flash_view_model.py:482-485)_ — The 80-line builder is wrapped in `except Exception: print(); return None`, so drive enumeration, image-open, or keygen failures collapse into a no-op WRITE button with no error surfaced.
> **#19** _(orchestrator.py:119-165)_ — Win32 paths raise bare `OSError`, which escapes `except ImagerError`, strips the SDState taxonomy, and (in `PairFlashJob`) yields `IndexError` masking the real cause.
> **#20** _(app.py:22-30, 145-148)_ — If the startup-log open fails in a frozen build, `sys.stderr` stays `None` and the unconditional boot writes raise `AttributeError`, crashing the GUI before the window appears — the exact scenario the log was meant to capture.
> **#21** _(AstromechOSImager.iss:18-46)_ — Without `AppMutex`/`SetupMutex`, the installer can run during an active flash; even though Windows blocks overwriting loaded DLLs, partial bundle replacement after the app exits is a real hazard.
> **#22** _(AstromechOSImager.iss:37-38)_ — `x64compatible` was introduced in Inno Setup 6.3.0; following the documented "6.2+" prerequisite produces a hard `Unknown architecture identifier` build failure.
> **#23** _(Theme.js:18)_ — Orbitron at 12 px for body copy hurts legibility and breaks the title/body hierarchy, penalising ESL and low-vision users on every secondary description string.
> **#24** _(Step1Mode.qml:32-52)_ — `SelectableCard` is `Rectangle` + `MouseArea` with no Tab focus, focus ring, or Space/Enter handler; keyboard-only users cannot change the flash mode off the default.
> **#25** _(main.qml:146-169)_ — Theme/min/max/close are pure glyphs with no `ToolTip`, no `Accessible.name`, no keyboard activation, and an ambiguous `❐`/`▢` maximise-state swap.
> **#26** _(Step2Images.qml:46-72)_ — `#5ec07a` on the light-theme `#ffffff` card yields ~2.3:1 contrast for the 10 px bold success badge — the most safety-critical confirmation in the wizard is the least readable.

### Medium

| # | File:Line | Dimension | Title | Fix |
|---|-----------|-----------|-------|-----|
| 27 | `astromechos_imager/ui/wizard_state.py:159-225` | correctness | Stale role-check verdicts can clobber a newer selection | Tag each `_kick_role_check` with a generation token (or carry the path in the signal) and discard late results that don't match the current selection. |
| 28 | `astromechos_imager/core/image_validator.py:265-266` | correctness | Image smaller than 512 bytes reported as MissingRoleMarkerError | Raise `MalformedRoleMarkerError(path.name, "image too small for an MBR")` so the wizard treats it as a hard block. |
| 29 | `astromechos_imager/core/keygen.py:76-85` | correctness | load_persisted_pair returns silently corrupted Ed25519Pair | Validate the loaded bytes (regex on `.pub`, PEM header on `.priv`); on mismatch return `None` to force regeneration. |
| 30 | `astromechos_imager/ui/wizard_state.py:204-225` | resources | Role-check daemon threads orphan temp files on app shutdown | Track in-flight check threads, cancel them on `aboutToQuit`, and sweep leftover `astromech_marker_*.img` from `%TEMP%` on startup. |
| 31 | `astromechos_imager/core/diskwriter.py:47-100` | resources | DiskWriter producer thread keeps source generator alive on consumer error | On consumer exception, set `self.cancel` so the producer unblocks; use `q.put(chunk, timeout=…)` to re-check the cancel flag instead of blocking forever. |
| 32 | `astromechos_imager/core/orchestrator.py:237-250` | resources | PairFlashJob parallel threads have no join timeout or exception propagation | Capture `(result, exc)` from each thread target, check exceptions after join before indexing, and add a try/finally teardown for held resources. |
| 33 | `astromechos_imager/core/image_validator.py:304-328` | validation | find_sidecar_checksum reads entire sidecar file into memory and ignores UTF-8 BOM | Read at most 8 KB binary, decode with `utf-8-sig`, then validate; also lstrip BOM defensively before regex match. |
| 34 | `astromechos_imager/core/image_validator.py:127-136` | validation | Role marker JSON parsing has no size or recursion bound; RecursionError bypasses MalformedRoleMarkerError | Cap marker size (e.g. 64 KB) before decoding and catch `RecursionError`/`ValueError` alongside `JSONDecodeError`, re-raising as `MalformedRoleMarkerError`. |
| 35 | `astromechos_imager/core/image_validator.py:270-292` | errors | Two broad `except Exception` blocks turn any MBR/pyfatfs failure into MalformedRoleMarkerError | Narrow to `BootPartitionMountError` for MBR parsing and the pyfatfs exception family for mount; let unexpected exceptions propagate. |
| 36 | `astromechos_imager/ui/app.py:166-176` | errors | DriveListModel bring-up swallows every exception with no log or recovery hint | Log the traceback to stderr (already redirected to `startup.log` in frozen builds) and expose a sentinel to QML so the wizard can render an actionable message. |
| 37 | `astromechos_imager/ui/qml/R2HeadIcon.qml:18` | polish | R2 icon stroke colour is hardcoded — doesn't track theme accent in light mode | Bind `strokeColor: theme.colors.colorAccent` in each R2 icon so the inner `ShapePath` bindings re-evaluate on `paletteChanged`. |
| 38 | `astromechos_imager/ui/qml/AstroButton.qml:79-103` | polish | AstroButton has hover and pressed states but no focus indicator | Add a focus-visible Rectangle bound to `visible: btn.activeFocus` (e.g. `colorAccentBright` border, slight outset) so Tab focus is visible. |
| 39 | `installer/AstromechOSImager.iss:18-46` | build | No SignTool placeholder / signing hooks — not ready for code signing | Add a `SignTool=mysigntool $f` placeholder, document the `iscc /S…` invocation in BUILD_INSTRUCTIONS.md, and add a signing step for the PyInstaller exe (don't unconditionally set `SignedUninstaller=yes`). |
| 40 | `installer/AstromechOSImager.iss:18-46` | build | No MinVersion — installer accepts unsupported Windows releases | Set `MinVersion=10.0.17763` to match PySide6 6.7's documented Win10 1809 floor and note the OS minimum in BUILD_INSTRUCTIONS.md. |
| 41 | `astromechos_imager.spec:37-40` | build | vendor/ shipping logic copies any non-blocklisted file — fragile excludes | Flip the denylist to an extension + name allowlist (covering required transitive DLLs and license texts) and warn at build time on unexpected vendor files. |

> **#27** _(wizard_state.py:159-225)_ — Two rapid image picks spawn two daemon threads; whichever finishes last wins, so a stale verdict for image A can overwrite the correct verdict for image B and gate NEXT incorrectly.
> **#28** _(image_validator.py:265-266)_ — Sub-512-byte (fully truncated) images surface as `MissingRoleMarkerError`, which the wizard policy reduces to amber — a corrupt source can sail past validation as a soft warning.
> **#29** _(keygen.py:76-85)_ — `load_persisted_pair` only checks existence; truncated or hand-edited key files are wrapped into an `Ed25519Pair` and flashed onto a card whose first-boot SSH will then fail irreversibly.
> **#30** _(wizard_state.py:204-225)_ — Daemon role-check threads create 128 MB `NamedTemporaryFile` artifacts; on interpreter shutdown their `finally` cleanup is not guaranteed to run, slowly polluting `%TEMP%`.
> **#31** _(diskwriter.py:47-100)_ — When the consumer raises (e.g. a short write), the producer blocks on a full bounded queue forever, `t_p.join()` hangs `run()`, and the source generator (and its zipfile handle) stays pinned indefinitely.
> **#32** _(orchestrator.py:237-250)_ — Plain threads with no exception capture mean an unexpected `OSError` in either job yields an empty result list and an `IndexError` on the join site, masking the real cause from CLI and UI alike.
> **#33** _(image_validator.py:304-328)_ — `read_text` has no size cap (multi-GB misnamed sidecar = OOM) and decodes plain UTF-8, so a PowerShell-emitted BOM silently invalidates an otherwise legitimate sidecar.
> **#34** _(image_validator.py:127-136)_ — Deeply nested JSON markers raise `RecursionError`, not `JSONDecodeError`; the wizard's bare-except downgrades that to amber "marker absent", contradicting the documented hard-block contract.
> **#35** _(image_validator.py:270-292)_ — Broad `except Exception` blocks around MBR-parse and pyfatfs mount steer the operator toward "re-extract the image" remediation even when the real failure is transient I/O or a library bug.
> **#36** _(app.py:166-176)_ — `except Exception: pass` makes the wizard show an empty Step 3 with no diagnostic — operators can't distinguish "no card inserted" from "WMI broken" or "pywin32 missing".
> **#37** _(R2HeadIcon.qml:18)_ — `strokeColor: "#5e9bd6"` is the dark-theme cyan; in light mode the accent palette shifts to cobalt while the icon stays cyan, breaking the R2 family identity on Step 1.
> **#38** _(AstroButton.qml:79-103)_ — Hover/press states are styled but `activeFocus` is not, so Tab-navigated users have no visual cue which button is focused — particularly dangerous on the Step 4 ERASE & WRITE confirm dialog.
> **#39** _(AstromechOSImager.iss:18-46)_ — Shipping an unsigned admin-elevated installer triggers SmartScreen "unrecognized publisher" warnings and lacks hooks for the inner PyInstaller exe — and README advertises signing docs that don't exist.
> **#40** _(AstromechOSImager.iss:18-46)_ — With `MinVersion` unset, Inno permits Win7+, so unsupported OSes install successfully and then crash later inside `win32com.client` or `pywin32` with no clear cause.
> **#41** _(astromechos_imager.spec:37-40)_ — A denylist of just three names lets PDBs, `.bak` files, and stray docs ship into the installer once an operator populates `vendor/` per `MISSING_BINARIES.md`.

### Low

| # | File:Line | Dimension | Title | Fix |
|---|-----------|-----------|-------|-----|
| 42 | `astromechos_imager/cli/main.py:48-54` | security | relaunch_as_admin builds parameters via unquoted space-join — argv smuggling | Use `subprocess.list2cmdline(sys.argv)` to apply Windows quoting rules; keep `argv[0]` for the `python -m` developer path. |
| 43 | `astromechos_imager/ui/qml/Step2Images.qml:52-57` | qml | Role-badge `checking` pulse leaves opacity wherever the last frame stopped | Add `onRunningChanged: if (!running) opacity = 1.0` on the SequentialAnimation (or pin opacity to 1 via a Behavior). |
| 44 | `astromechos_imager/ui/flash_view_model.py:446-451` | validation | Drive lookup uses .get() but never reports the failure when ID became stale | Raise `DriveNotFoundError` at the `.get()` boundary so the UI ErrorDialog surfaces a clean "card was removed" message (and ensure the build-time `except` propagates it). |
| 45 | `astromechos_imager/core/bootpartition.py:182-186` | errors | PyFatFsBootPartition.close swallows all exceptions | Log the exception at warning level and consider re-raising as a non-fatal `CleanupError` so the orchestrator records the post-trigger flush failure. |
| 46 | `astromechos_imager/ui/wizard_state.py:218-220` | errors | Role-check daemon swallows any unexpected exception and lies about it as 'unknown_marker_absent' | Log the exception and set a new `check_failed` status that the wizard treats as a hard block, not a soft warning. |
| 47 | `astromechos_imager/core/errors.py:44-45` | errors | Docstring claims recovery_hint is French but the strings are English | Update the comment to "The recovery_hint is in English (operator-facing) and ends up under the file picker / inside the ErrorDialog." |
| 48 | `astromechos_imager/ui/flash_view_model.py:113-114` | errors | Hash worker encodes exception into the digest channel as 'ERR:Type:message' | Add a dedicated `error = Signal(str, str)` on `_HashWorker` and route exceptions through it; log full traceback via the JSONL logger before emitting. |
| 49 | `astromechos_imager/ui/qml/main.qml:271-291` | polish | Resize grip is 14×14, in the corner only — no resize affordance on the edges | Add four thin edge `MouseArea`s calling `startSystemResize(<edge>)` with matching cursors, or enlarge the corner grip to 24×24. |
| 50 | `installer/AstromechOSImager.iss:10-16` | build | AppVersion duplicated from pyproject.toml — sync drift waiting to happen | Single-source the version (generated `version.iss` include or preprocessor regex over `pyproject.toml`) and include `astromechos_imager/__init__.py` in any sync script. |

> **#42** _(cli/main.py:48-54)_ — `" ".join(sys.argv)` skips Windows quoting; image paths containing spaces fragment across `CommandLineToArgvW` in the elevated child. Real defect, but the production EXE already ships with `requireAdministrator` so the impact is bounded to the developer `python -m` path.
> **#43** _(Step2Images.qml:52-57)_ — When the badge status leaves `"checking"`, the SequentialAnimation stops mid-cycle and the dot can remain half-transparent until the next status change, hurting the green-✓/red-✗ readability.
> **#44** _(flash_view_model.py:446-451)_ — A drive yanked between Step 3 and Step 4 yields `target=None` silently, eventually surfacing as `AttributeError: 'NoneType' object has no attribute 'drive_letters'` after wasted hash time.
> **#45** _(bootpartition.py:182-186)_ — Swallowing `_fs.close()` errors after the `/ASTROMECH_FIRSTBOOT_READY` trigger is written means a card with un-flushed FAT metadata can be reported as a successful flash.
> **#46** _(wizard_state.py:218-220)_ — Internal errors (missing pyfatfs, decompression corruption, transient I/O) are presented as the amber "no marker" soft-pass operators are documented to override, weakening the only role-safety gate before a destructive write.
> **#47** _(errors.py:44-45)_ — Stale French-era comment misrepresents the contract for future maintainers; comment-only fix with no runtime impact.
> **#48** _(flash_view_model.py:113-114)_ — Overloading the digest slot with `ERR:Type:message` mixes data and error channels and discards the traceback; safe by accident (`hexdigest()` is hex-only), but worth a dedicated signal and a `logger.exception`.
> **#49** _(main.qml:271-291)_ — `FramelessWindowHint` drops native edge resize; the lone 14 px corner grip is below the Win11 24 px target and offers no left/top/bottom affordance.
> **#50** _(AstromechOSImager.iss:10-16)_ — Three independent version sources (`.iss`, `pyproject.toml`, `__init__.py`) will drift; the suggested `ReadIni`/`GetStringFileInfo` snippets are partially wrong (TOML ≠ INI), but the direction of single-sourcing is correct.

### Info

| # | File:Line | Dimension | Title | Fix |
|---|-----------|-----------|-------|-----|
| 51 | `astromechos_imager/core/customization.py:85-95` | security | render_wlan_conf does not escape SSID/PSK shell metacharacters | Single-quote the values and escape embedded `'` (`SSID='foo'\''bar'`), or document the file as awk-only (KEY=VALUE) and ensure `firstboot_setup.sh` parses with `awk -F=` rather than `source`. |

> **#51** _(customization.py:85-95)_ — `f"SSID={ssid}\nPSK={psk}\n"` is documented as "shell-sourceable" but the validators allow `$`, backticks, `;`, and even embedded newlines — a contractual gap with no current exploitation path on the local single-operator threat model, but worth hardening at the renderer.

### Bonus — Critical surfaced under "high"

| # | File:Line | Dimension | Title | Fix |
|---|-----------|-----------|-------|-----|
| 52 | `astromechos_imager/ui/flash_view_model.py:417-419` | correctness | _build_flash_job imports nonexistent generate_linux_account (already listed as #1) | See finding #1. |

_(Note: finding #1 already covers this case.)_

86 refuted candidates were dropped after adversarial review.