# AUDIT CHIRURGICAL AstroMechOS_Imager — ÉTAT PHASE 1 (2026-06-11)

> **Marqueur de reprise : `REPRISE-AUDIT-IMAGER-1106`** (mémoire beads du même nom pointe ici).
> Audit READ-ONLY — aucun fichier modifié. Repo @ `69b836b`, working tree clean.
> Phase 1 = TERMINÉE (cartographie + points de rupture, claims HIGH vérifiés de première main).
> Phase 2 (autopsie narrative des 3 bugs cibles) = matière première prête, à rédiger.
> Phase 3 (plan de refactoring) = à produire à partir de la fix-list priorisée en fin de doc.

---

## 0. Méthode + fichiers couverts

3 agents d'audit parallèles (axes : lancement/popup · cycle de vie lecteur/handles · auto-détection/dead-code), puis vérification directe des claims HIGH par lecture du code.

**Fichiers lus intégralement** : `ui/app.py` (325), `ui/wizard_state.py` (639), `ui/flash_view_model.py` (805), `ui/drive_list_model.py` (156), `platform/windows.py` (1098), `platform/_win32.py` (168), `platform/native_shell_quiet.py` (108), `core/orchestrator.py` (532), `core/diskwriter.py` (292), `core/raw_sector_io.py` (103), `core/platform_io.py` (35), `core/bootpartition.py` (218), `core/raw_fat_partition.py` (153), `core/models.py` (104), `cli/main.py` (130), `ui/qml/Step4Role.qml`, `main.qml`, tests clés (`test_app_launch`, `test_handle_idempotency`, `test_lock_dismount`, `test_wizard_state_*`, `test_drive_enum`, `test_flash_view_model_defaults`).

**Vérifiés de première main par l'orchestrateur** (pas seulement par agent) :
`windows.py:916-927` (_run_mountvol), `:930-955` (disable/enable_automount), `:958-966` (restore_if_crashed), `:20` (_MAX_SD_BYTES), `app.py:140-238` (séquence launch + mutex + aboutToQuit), `Step4Role.qml:29,49-73,422` (auto-select), zéro caller de `attach_letter_to_unmounted_volume` hors façade/Protocol.

---

## 1. Cartographie du lancement (T0 → wizard interactif)

| T | Événement | Localisation |
|---|---|---|
| T0 | Redirect stdout/stderr → `%LOCALAPPDATA%\AstromechOS_Imager\startup.log` (frozen) | `app.py:24-31` |
| T1 | Import PySide6 (module-level, 1-3 s frozen) | `app.py:33-36` |
| T2 | `setup_logging()` JSONL | `app.py:358-368` |
| T3 | `SetErrorMode(SEM_FAILCRITICALERRORS\|SEM_NOOPENFILEERRORBOX)` — in-process seulement | `app.py:142-149` → `windows.py:476-504` |
| T5 | `restore_automount_if_crashed()` → si marker : **`mountvol /E`** | `app.py:180` → `windows.py:958-966` |
| T6 | `disable_automount()` → `mountvol /N` + marker `%LOCALAPPDATA%\...\automount_disabled.marker` | `app.py:181` → `windows.py:930-944` |
| T8 | `QGuiApplication` créée | `app.py:198` |
| T9 | `aboutToQuit → enable_automount()` (SEUL point de restore normal-exit) | `app.py:209-214` |
| T10 | `CreateMutexW("Global\\AstromechOS_Imager_AppMutex")` — résultat **jamais testé**, gated `sys.frozen` | `app.py:224-238` |
| T11 | `WizardState(release_disk_letters=hook)` injecté | `app.py:264-284`, `wizard_state.py:102-171` |
| T12-13 | `engine.load(main.qml)` + `QTimer.singleShot(0, _bring_up_drive_model)` | `app.py:306,353` |
| T14 | 1er tick event-loop : `DriveListModel.refresh()` **synchrone main-thread** (WMI `Win32_DiskDrive` + ASSOCIATORS), puis poll 2 s | `drive_list_model.py:65-102`, `windows.py:24-134` |
| T15 | Splash 4000 ms → wizard à 4300 ms | `main.qml:298-303,354-362` |

**Fenêtres de vulnérabilité** : W1 = T0→T6 (import Python, automount encore ON) · W2 = T5→T6 (gap `/E`→`/N` si marker stale) · W3 = toute la session avant Step 4 (carte insérée AVANT le launch garde ses lettres — `mountvol /N` ne démonte pas l'existant ; release seulement à la sélection du disque concerné).

---

## 2. POINTS DE RUPTURE IDENTIFIÉS (tous vérifiés, file:line)

### Axe A — Ghost Popup au démarrage

| Sév | ID | Défaut | Où |
|---|---|---|---|
| HIGH | A1 | **Poll WMI 2 s matérialise `Win32_LogicalDisk` sur le volume RAW/ext4 lettré** d'une carte insérée pré-launch — depuis **WmiPrvSE.exe** (hors process → `SetErrorMode` inopérant). 1er tick + toutes les 2 s = popup format re-déclenchable. | `windows.py:33-50`, `drive_list_model.py:72-76`, `app.py:353` |
| HIGH | A2 | **Marker stale → `mountvol /E` au launch** : toute session précédente killée (Task Manager, Ctrl+C, debugger — aucun ne fire `aboutToQuit`) laisse le marker → le prochain launch RÉACTIVE l'automount, la carte ext4 pré-insérée se monte dans le gap `/E`→`/N` → popup au démarrage. **C'est le scénario opérateur le plus probable (A2+A1 composés).** | `app.py:180-181`, `windows.py:958-966` |
| HIGH | A3 | **`_run_mountvol` ne vérifie JAMAIS le returncode** — retourne True dès que le process spawn. `mountvol /N` exige l'élévation : run non-élevé → échec silencieux, log dit "automount disabled", marker écrit, session entière avec automount réellement ON. Docstring (`:934-935`) mensongère. stdout/stderr capturés puis jetés. | `windows.py:916-927,937-944` |
| MED | A4 | **Pas de gate single-instance** : mutex créé mais `ERROR_ALREADY_EXISTS` jamais testé ; le marker confond "session active" et "crashée" → 2e instance fait `/E` sous les pieds de la 1re ; le quit de N'IMPORTE laquelle réactive l'automount + supprime le marker. | `app.py:224-238,180` |
| MED | A5 | **`enable_automount` supprime le marker même si `/E` a échoué** (retour ignoré, return True inconditionnel) → machine avec automount OFF en permanence, silencieusement. | `windows.py:947-955` |
| MED | A6 | `mountvol` bloquant main-thread AVANT Qt/splash (jusqu'à 45 s worst case, 3 spawns × 15 s timeout). | `app.py:180-181`, `windows.py:921` |
| MED | A7 | Tests UI (`test_app_launch.py`) exécutent les VRAIS mountvol/marker sur la machine dev (aucun seam d'injection dans `build_app`). | `tests/ui/test_app_launch.py`, `app.py:175-183` |
| LOW | A8 | Marker per-user (`%LOCALAPPDATA%`) vs réglage system-wide ; restore jamais garanti si l'app n'est pas relancée. | `windows.py:905-913` |

### Axe B — Lecteur captif dans l'Explorateur

**Le lecteur captif N'EST PAS un handle leaké — c'est l'état final CONÇU.** Aucun `FSCTL_LOCK_VOLUME` ne survit à `lock_and_dismount` (lock→dismount→unlock→close par volume, retourne toujours `[]`, `windows.py:276-296,339`). L'inventaire handle est sain (orchestrator double-`finally` `orchestrator.py:246-250,325-329` ; idempotence pinnée par `test_handle_idempotency`).

| Sév | ID | Défaut | Où |
|---|---|---|---|
| HIGH | F1 | **Aucune restauration de lettre sur AUCUN chemin.** Succès : `finalize_eject` échoue sur la plupart des bridges SD (docstring l'admet) → rien d'autre ne se passe ; lettre purgée de MountedDevices ; automount OFF → carte létterless jusqu'à réinsertion physique. `mountvol /E` au quit ne re-monte PAS les volumes déjà présents. L'outil exact (`attach_letter_to_unmounted_volume`, `windows.py:636-710`) existe avec **zéro caller**. | `orchestrator.py:250-261`, `windows.py:862-888,636-710` |
| HIGH | F2 | **Recovery cancel/échec contredit la politique automount** : `restore_readable_exfat` omet `assign` de diskpart en comptant sur l'automount ("Windows picks a free letter") — mais l'automount est OFF toute la session → carte reformatée exFAT **invisible** ; l'opérateur croit la carte brickée. | `windows.py:752-780`, `orchestrator.py:345-364` |
| HIGH | F4 | **Quit mid-flash non gardé** : aucun `onClosing` QML, rien ne connecte `aboutToQuit`→`cancel()` ; quitter pendant l'écriture fire `enable_automount` PENDANT le stream (Windows peut monter la carte à moitié écrite → popup), supprime le marker, et tue le QThread writer → carte RAW, `restore_readable_exfat` jamais exécuté. | `flash_view_model.py:379-386`, `main.qml:186`, `Step7Complete.qml:194`, `app.py:209-214` |
| MED | F3 | **`SHChangeNotify` partiel + gated DLL** : fired seulement dans `lock_and_dismount` ET seulement si `astro_flash.dll` présente (dégrade en no-op silencieux). Le release Step-4 et `force_unmount_letter` ne notifient JAMAIS le shell → Explorer garde une icône `K:` morte qui erreur au clic = « captif pendant le run ». | `windows.py:325-332`, `native_shell_quiet.py:50-77`, `app.py:271-282` |
| MED | R1 | **Thread daemon release Step-4 vs flash : zéro synchronisation** (pas de join/lock/génération). Flash lancé pendant que le daemon tient un handle volume GENERIC_WRITE en retry-loop → les retries `FSCTL_LOCK_VOLUME` du flash échouent (2 s brûlées) → fallback "dismount anyway". | `wizard_state.py:437,444,476-477`, `windows.py:581-587,276-283` |
| MED | R2 | **Poll WMI reprend pendant `"cancelling"`** : pause uniquement sur `("verifying","flashing")` ; cancel flippe le status immédiatement pendant que le worker exécute encore diskpart clean/format sur le disque RAW → poll ASSOCIATORS main-thread race diskpart. | `app.py:336-341`, `flash_view_model.py:653`, `orchestrator.py:345-357` |
| MED | R3 | `disable_automount()` retour ignoré aux 2 call sites (cf. A3) → défense mid-flash repose alors uniquement sur le MBR différé. | `app.py:182`, `orchestrator.py:109-113` |
| LOW | B5 | `CloseHandle` inline (pas de `finally`) dans `lock_and_dismount` (`:271-296`) et `force_unmount_letter` (`:578-597`) ; `thread.wait(500)` puis drop de la ref QThread (`flash_view_model.py:511-515,702-706`) → GC d'un QThread vivant = fatal Qt. | — |

### Axe C — Auto-détection / sélection par défaut

| Sév | ID | Défaut | Où |
|---|---|---|---|
| HIGH | C1 | **Le SSD USB 256 GB de l'opérateur (qui héberge les images !) passe tous les filtres** : gate = `InterfaceType=="USB"` **OU** removable (`windows.py:92-96`) ; cap `_MAX_SD_BYTES = 256 GiB` (`windows.py:20`) > 256 GB décimaux du SSD. Pas d'exclusion du disque-source des images. Seul présent → **auto-sélectionné sans clic** + lettres force-démontées → archive d'images disparaît d'Explorer pour la session. À 1 clic du flash. Mitigations existantes non-conçues : banner "MULTIPLE SD CARDS" si ≥2, et le dismount ferait échouer la lecture du hash. | `windows.py:20,92-121`, `Step4Role.qml:67-73` |
| HIGH (confirmé) | C2 | **Auto-sélection zéro-clic** dès `driveCount==1` : `_autoSelectImposed()` à `Component.onCompleted` + `onImposedRoleChanged` + `onDriveCountChanged` → `setMasterDriveId(firstDriveId)` → fire le release-letters destructif sans action opérateur. | `Step4Role.qml:54-73` |
| MED | C3 | **Stale-id au swap de carte** : re-assignation seulement si `currentRole !== imposedRole` ; pull carte A / insert carte B → l'UI affiche B, `masterDriveId` vaut encore A ; NEXT reste actif. Si Windows recycle le numéro de disque (même slot) → flash de B « par chance » ; sinon erreur "drive not found" au WRITE. Aucun handler `onFirstDriveIdChanged`. | `Step4Role.qml:67-73`, `flash_view_model.py:860-865` |
| OK | C4 | Flux pair Master→Slave : propre. `resetForNextCycle` clear les 2 drive ids (`wizard_state.py:552-566`), `endSession` wipe complet + re-mint SSID (`:527-550`) ; pinné par `test_wizard_state_sequential.py`. Clear `(-1)` ne fire pas le hook release (`:462`). | — |

### Axe D — Dead code / redondances (cibles ULW)

**Morts (zéro caller production)** : `_create_volume_handle` (`windows.py:166-180`) · `attach_letter_to_unmounted_volume` (+ helpers transitifs `_volume_has_letter:423`, `_volume_has_recognised_fs:441` ; ironiquement = l'outil dont F1/F2 ont besoin) · `eject_media` (`:857-859`) · `update_disk_properties` (`:741-743`) · chemin α complet `bootpartition.py:163-279` (`DriveLetterBootPartition`, `wait_for_new_drive_letter`, `open_boot_partition`) · `load_persisted_hotspot` (`keygen.py:258`) · `build_diagnostic_zip`/`collect_system_info` (`diagnostic.py:62,90` — feature sans surface UI/CLI) · `WizardState.reuseHotspot` (`wizard_state.py:57,604-612`) · `_PlainRawDevice.SECTOR` (`windows.py:1065`) · boucle `locked_handles` no-op permanent (`orchestrator.py:90,124-129,330-339`).

**Scripts bit-rotted** : `e2e_diag_readback.py:80` + `e2e_probe_write_8mb.py:73` (TypeError — signature `attach_letter…` changée) · `diag_held_lock_write.py` (prémisse morte — held-lock reverté, boucle sur liste vide).

**Drift constantes/CLI** : secteur 512 défini 3× · `cli/main.py:30` default `--install-user="pi"` **contredit** l'invariant GUI `astromech` (`flash_view_model.py:794-799`) · `cli/main.py:100` hardcode `imager_version="0.1.0"` vs `__init__.py:3` · **le GUI ne renseigne jamais `imager_version`/`flashed_at_iso`** → cartes flashées GUI ont des blancs dans le header généré (`models.py:90-91`, `customization.py:69-70`) · CLI ne passe pas `linux_account` → pas de provisioning compte (`orchestrator.py:469-482`) · CLI expose encore `PairFlashJob` (parallèle) supprimé du GUI · dérivation `%LOCALAPPDATA%` copy-pastée (`app.py:12-16` vs `windows.py:905-913`) · Protocol `PlatformIO` périmé dans les 2 sens (`platform_io.py:38-48` : déclare les morts, omet `finalize_eject`/`restore_readable_exfat`/`letters_on_disk`/`force_unmount_letter`/`disable_automount`/`sync_cache`/`open_plain_raw_device` consommés par duck-typing).

**Commentaires périmés** : `orchestrator.py:97-107` + `app.py:202-208` décrivent le design pré-c6d2497 (automount au flash-click) · `app.py:300-302` ("after splash" faux — singleShot(0) = 1er tick) · `windows.py:643-644` (claim `update_disk_properties` exécuté — faux).

---

## 3. SYNTHÈSE NARRATIVE (pré-Phase 2)

- **Ghost Popup** = composition A2+A1 : kill de session précédente → marker stale → `/E` au launch suivant → la carte ext4 pré-insérée (re)monte → le poll WMI 2 s + Explorer la sondent depuis des process hors de portée de `SetErrorMode`. A3 (returncode ignoré) rend tout le système de défense non-fiable en run non-élevé.
- **Lecteur captif** = état final conçu, pas un leak : lettres purgées (sélection + flash), automount OFF session, jamais de re-attach (F1), recovery exFAT invisible (F2), shell jamais notifié hors flash+DLL (F3).
- **Auto-détection** = zéro-clic dangereuse : filtre OR-USB + cap GiB laisse passer le SSD-source (C1), auto-select fire un dismount destructif sans action opérateur (C2), stale-id au swap (C3).

## 4. FIX-LIST PRIORISÉE (input Phase 3)

1. **A3/A5/R3** — vérifier returncode mountvol + logger stderr ; ne supprimer le marker que si `/E` OK ; warn UI si `/N` échoue (élévation).
2. **A2/A4** — single-instance via le mutex existant (tester `ERROR_ALREADY_EXISTS`) ; marker = "session active" seulement si pas d'instance vivante ; ne pas faire `/E` si une instance tourne.
3. **C1** — exclure `MediaType` fixed (sauf confirmation explicite), exclure le disque hébergeant `masterImagePath`/`slaveImagePath`.
4. **C2/C3** — re-assigner sur `onFirstDriveIdChanged` OU valider `masterDriveId===firstDriveId` dans le gate NEXT ; envisager confirmation avant le release destructif.
5. **F2** — `assign` dans le script diskpart de `restore_readable_exfat` (ou appeler `attach_letter_to_unmounted_volume`).
6. **F1** — au succès, si `finalize_eject` False : re-attach lettre boot OU message UI "retirer/réinsérer la carte".
7. **F4** — `onClosing` QML : si status ∈ {verifying,flashing,cancelling} → confirmer + cancel + join AVANT `enable_automount`.
8. **A1** — release des lettres de TOUS les candidats removable au 1er scan (l'énumération exclut déjà system-disk) OU ne pas requêter les lettres des volumes RAW dans le poll.
9. **F3** — fire `SHChangeNotify` depuis release Step-4 + `force_unmount_letter` ; log fort si DLL absente.
10. **R1/R2** — garder le Thread release sur WizardState + join au preflight ; inclure `"cancelling"` dans le pause-set du poll (`app.py:338`).
11. **A6** — déplacer les mountvol launch hors main-thread (post-splash) ou réduire le timeout.
12. **D** — purge dead code (§D), sync Protocol, CLI importe `DEFAULT_*`/`__version__` + passe `linux_account`, GUI renseigne `imager_version`/`flashed_at_iso`, fix/delete les 3 scripts bit-rotted, MAJ commentaires périmés.
13. **A7** — seam d'injection dans `build_app()` pour neutraliser mountvol/marker/WMI sous pytest.

## 5. REPRISE — quoi faire ensuite

- **Phase 2** : rédiger l'autopsie narrative ("pourquoi" de chaque bug) — toute la matière est au §2/§3.
- **Phase 3** : transformer la fix-list §4 en plan de refactoring séquencé (commits atomiques, tests d'abord — le repo a 112 tests verts comme baseline ; `python -m pytest` dans le repo Imager).
- Agents réutilisables via SendMessage : launch=`acae4b4194c0f0212`, lifecycle=`a6b295a99c72ba7ef`, autodetect/deadcode=`a46b39bb18f9694b3` (valides seulement dans la session d'origine).
- Contexte parallèle : flash des 2 cartes SD avec build 0.1.0 en suspens (voir mémoire `reprise-flash-1106-...`).
