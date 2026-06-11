# AUDIT PHASE 3 — PLAN DE REFACTORING & POLISH (2026-06-11)

> **Marqueur de reprise : `REPRISE-AUDIT-IMAGER-1106`** · Prérequis : Phase 1 (cartographie) + Phase 2 (autopsie) dans `docs/`.
> Objectif : démarrage **silencieux**, app **hyper stable/rapide**, code **robuste/fiable**.
> Baseline : 112 tests verts (`python -m pytest` à la racine du repo Imager). Chaque WP = commit(s) atomique(s), tests AVANT merge, full pytest après chaque WP.
> Ordre = risque décroissant × dépendances. WP1→WP2 d'abord (fondations de vérité), le reste peut se paralléliser.

---

## WP1 — La frontière win32 dit la vérité (cause racine #1) — A3/A5/R3

**Fichiers** : `platform/windows.py:916-966`, call sites `ui/app.py:175-183`, `core/orchestrator.py:108-113`.

1. `_run_mountvol(flag)` → retourne `(ok: bool, rc: int, stderr: str)` ; `ok = (proc.returncode == 0)` ; log WARNING avec rc+stderr tronqué si échec (plus jamais jeté).
2. `disable_automount()` : n'écrit le marker QUE si ok (honore enfin sa docstring). Retourne ok.
3. `enable_automount()` : ne supprime le marker QUE si `/E` ok ; sinon log ERROR + conserve le marker (trace de réparation). Retourne ok.
4. Call sites : `app.py:182` et `orchestrator.py:109-113` testent le retour ; si False → flag `automount_defense_active=False` exposé au FlashViewModel → bandeau UI discret "Protection automount inactive (lancer en administrateur)" sur Step 4/5.
5. Détection d'élévation explicite au boot (`ctypes.windll.shell32.IsUserAnAdmin()`) → même bandeau, log INFO.

**Tests** : unit avec `subprocess.run` mocké (rc 0/1/timeout/FileNotFound) ; marker présent/absent selon ok ; pas de marker orphelin. ~6 tests.
**Taille** : S (½ journée). **Risque** : nul (resserre des contrats existants).

## WP2 — Modèle de session pour l'état global machine (cause racine #4) — A2/A4

**Fichiers** : `ui/app.py:175-238`, `platform/windows.py:905-966`. Nouveau : `platform/session_guard.py`.

1. Classe `AutomountSessionGuard` : propriétaire unique du triplet {mutex, marker, automount}.
   - `acquire()` : `CreateMutexW` + **teste `GetLastError()==ERROR_ALREADY_EXISTS`**.
     - Si déjà une instance → dialogue "AstromechOS Imager est déjà lancé" → exit propre (AUCUN `/E`, AUCUN toucher au marker).
     - Sinon : si marker présent → vraie session crashée → `/E` réparateur PUIS `/N` (la fenêtre /E→/N reste, traitée par WP3-2 qui strippe les lettres juste après).
   - `release()` : `/E` + clear marker (si ok, cf. WP1).
2. `app.py` : remplacer les blocs `:175-183` + `:209-238` par le guard ; `aboutToQuit` → `guard.release()` **gated par WP5** (jamais pendant un flash).
3. Marker enrichi : contenu = PID + timestamp (diagnostic des doubles instances dans les logs).

**Tests** : unit avec mutex/win32 fakés — 2e instance ne touche ni `/E` ni marker ; marker stale + pas d'instance → repair ; clean exit → release. ~5 tests.
**Taille** : M (1 jour). **Dépend** : WP1.

## WP3 — Démarrage silencieux et rapide (Autopsie 1) — A1/A6 + perf

**Fichiers** : `ui/app.py:140-353`, `ui/drive_list_model.py:65-102`, `platform/windows.py:24-134`.

1. **mountvol hors main-thread** : `guard.acquire()` dans un QThread/thread démarré juste après la création de `QGuiApplication`, splash affiché IMMÉDIATEMENT. Timeout `_run_mountvol` 15→5 s. Gain : fenêtre visible en <1 s même si mountvol traîne (vs 45 s worst case actuel).
2. **Strip des lettres de TOUS les candidats au premier scan** (tue la chaîne A1 ET le résidu /E→/N de WP2) : après le premier `enumerate_removable_drives()`, pour chaque candidat → `force_unmount_letter` sur `letters_on_disk(id)` (COM-free, thread démon). L'énumération exclut déjà le disque système et >256 GiB — et WP6 la durcit encore avant ce strip. Le popup devient physiquement impossible : plus aucun volume RAW lettré ne survit au premier scan.
3. **Le poll ne touche plus les lettres** : `refresh()` périodique ne diffe que `(phys_id, size, model)` depuis `Win32_DiskDrive` SEUL (pas d'ASSOCIATORS → plus de matérialisation `Win32_LogicalDisk` → WmiPrvSE ne sonde plus rien). Les lettres ne sont requêtées qu'aux moments d'action (sélection/flash) via `letters_on_disk` (déjà COM-free).
4. **Premier refresh hors main thread** : `DriveListModel.refresh()` initial dans un worker (attention CoInitialize — pattern déjà géré `windows.py:1186-1196`) ; signal → update du model sur le main thread. Plus de blocage pré-paint.
5. Corriger le commentaire `app.py:300-302` (singleShot(0) ≠ "après splash").

**Tests** : unit DriveListModel avec PlatformIO fake (pas d'appel lettres dans le poll) ; e2e manuel : carte ext4 insérée AVANT launch + marker stale simulé → zéro popup. ~5 tests + 1 protocole manuel.
**Taille** : M-L (1-1,5 jour). **Dépend** : WP1, WP2.

## WP4 — Sortie propre : plus jamais de lecteur captif (Autopsie 2) — F1/F2/F3

**Fichiers** : `platform/windows.py:636-710,752-780,857-888`, `core/orchestrator.py:250-261,345-364`, `platform/native_shell_quiet.py:50-77`.

1. **F2 (cancel/échec)** : `restore_readable_exfat` → ajouter `assign` au script diskpart (1 ligne). La carte annulée redevient VISIBLE. C'est le quick-win n°1 de tout le plan.
2. **F1 (succès)** : après `finalize_eject()==False` → `attach_letter_to_unmounted_volume(boot_letter, drive_id)` (le code mort retrouve sa raison d'être ; il est déjà safety-filtré par drive id) + message Step 6/7 "Carte prête — vous pouvez la retirer". Si l'attach échoue → message "retirer/réinsérer la carte" (dégradation honnête).
3. **F3 (icône fantôme)** : extraire un helper `notify_shell_drive_removed(letter)` ; l'appeler depuis `force_unmount_letter` ET le release Step-4 ET `lock_and_dismount`. Si `astro_flash.dll` absente → log WARNING au boot (une fois), plus de no-op silencieux. Fallback sans DLL : `SHChangeNotify` direct via ctypes (shell32 est déjà chargée — évaluer en implémentant).
4. Mettre à jour `PlatformIO` Protocol (`core/platform_io.py:38-48`) : retirer les morts restants, ajouter tout ce que l'orchestrator consomme par duck-typing (`finalize_eject`, `restore_readable_exfat`, `letters_on_disk`, `force_unmount_letter`, `disable_automount`, `sync_cache`, `open_plain_raw_device`).

**Tests** : unit fakes — succès→attach appelé ; cancel→script diskpart contient `assign` ; DLL absente→warning loggé. Integration carte réelle : flash complet → carte visible dans Explorer à la fin SANS réinsertion ; cancel → carte exFAT visible. ~7 tests.
**Taille** : M (1 jour). **Indépendant** (parallélisable avec WP3).

## WP5 — Quit safety (F4) + races UI (R2)

**Fichiers** : `ui/qml/main.qml`, `Step7Complete.qml:194`, `ui/app.py:209-214,336-347`, `ui/flash_view_model.py:653,511-515,702-706`.

1. `onClosing` sur la fenêtre racine : si `status ∈ {verifying, flashing, cancelling}` → `close.accepted=false` + confirmDialog "Flash en cours — annuler et quitter ?" → si oui : `cancel()` → attendre fin worker (signal) → puis `Qt.quit()`.
2. `aboutToQuit` → `guard.release()` ne s'exécute que si aucun worker vivant (le gating de 1 le garantit ; ajouter assert/log défensif).
3. **R2** : pause-set du poll (`app.py:338`) étendu à `"cancelling"` + `"cancelled"`/`"error"` tant que le worker n'a pas join (exposer `workerAlive` du FlashViewModel plutôt que deviner par status).
4. **QThread GC fix** : remplacer `thread.wait(500)` + drop (`flash_view_model.py:511-515,702-706`) par `wait()` complet sur signal `finished` (ou parentage Qt) — un QThread GC'd vivant = crash Qt fatal aléatoire.

**Tests** : unit phases (fake worker lent → close refusé puis accepté) ; R2 : status "cancelling" → poll pausé. ~5 tests.
**Taille** : M (1 jour). **Dépend** : WP2 (guard).

## WP6 — Sélection sûre (Autopsie 3) — C1/C2/C3

**Fichiers** : `platform/windows.py:20,75-134`, `ui/qml/Step4Role.qml:29-73,422-424`, `ui/wizard_state.py:424-477`, `ui/flash_view_model.py:794-865`.

1. **C1 filtre** : (a) candidat `InterfaceType=USB` + `MediaType` contient "fixed" → marqué `suspect_ssd=True` ; exclu de l'auto-select, affiché avec badge "Disque fixe USB — vérifiez !" + confirmation explicite pour le sélectionner ; (b) **exclusion dure du disque hébergeant `masterImagePath`/`slaveImagePath`** : résoudre le volume des paths sources → disque physique → blacklist (l'API extents existe : `windows.py:507-559`) ; (c) garder le cap 256 GiB.
2. **C2 auto-select** : l'auto-sélection ne déclenche PLUS le release des lettres (retirer l'effet de bord du chemin auto ; WP3-2 a déjà strippé les lettres de tous les candidats au scan → le release à la sélection devient redondant → le **supprimer entièrement** de `setMasterDriveId`/`setSlaveDriveId` et garder les backstops flash-time `lock_and_dismount`+`_wait_for_unmount`). Simplification nette : moins de threads démon, R1 (race daemon vs flash) disparaît par construction.
3. **C3 stale-id** : `onFirstDriveIdChanged: _autoSelectImposed()` avec garde réécrite sur le DISQUE (`wizardState.{role}DriveId !== firstDriveId`) ; gate NEXT (`:422-424`) devient `hasOneCard && wizardState.currentDriveId === firstDriveId`.
4. CLI en lockstep : `cli/main.py:30,38,100` importe `DEFAULT_INSTALL_USER`/`DEFAULT_PASSWORD`/`__version__` ; passe `linux_account` ; GUI renseigne `imager_version=__version__` + `flashed_at_iso` dans `_build_flash_job` (`flash_view_model.py:836-845`).

**Tests** : unit enum (SSD fixe USB → suspect ; disque source → exclu) ; QML/state : swap A→B → id réassigné ; auto-select ne release plus ; NEXT gated. MAJ `test_wizard_state_release_letters` (sémantique changée). ~10 tests.
**Taille** : L (1,5-2 jours). **Dépend** : WP3 (strip au scan rend 2 possible).

## WP7 — Durcissement résiduel — R1/B5

(R1 disparaît si WP6-2 supprime le release à la sélection — sinon : garder le `Thread` sur `WizardState` + `join(timeout=3)` au preflight de `FlashJob`.)

1. `try/finally` autour des `CloseHandle` : `lock_and_dismount` (`windows.py:271-296`), `force_unmount_letter` (`:578-597`).
2. Supprimer la plomberie `locked_handles` no-op (`orchestrator.py:90,124-129,330-339`) — vestige du held-lock reverté.

**Tests** : unit exception mid-lock → handle fermé. ~3 tests. **Taille** : S (½ journée).

## WP8 — Seams de test (cause racine #5) — A7

**Fichiers** : `ui/app.py:build_app`, `tests/ui/test_app_launch.py`, `tests/conftest.py`.

1. `build_app(platform_adapter=None)` : injection du module win32 (default = réel). Pytest passe un fake → **plus aucun mountvol/marker/WMI réel sous CI**.
2. Fixture conftest qui interdit `subprocess.run(["mountvol",...])` en CI (monkeypatch sentinelle qui raise) — anti-régression structurel.

**Tests** : les 5 smoke tests existants migrent sur le fake ; nouveau test "aucun subprocess réel". **Taille** : S-M (½-1 jour). **Dépend** : WP2 (le guard est le point d'injection naturel).

## WP9 — Purge dead code + drift (ULW) — §D Phase 1

Après WP4/WP6 (qui ressuscitent `attach_letter_to_unmounted_volume`), supprimer :
`_create_volume_handle` (`windows.py:166-180`) · `eject_media` + façade + Protocol · `update_disk_properties` + façade + Protocol (sauf si WP4-2 l'utilise) · chemin α `bootpartition.py:163-279` (sortir `find_first_fat32_partition`+`BootPartitionLayout`, garder `PyFatFsBootPartition` si les fixtures en dépendent) · `load_persisted_hotspot` (`keygen.py:258`) OU le brancher (décision produit : réutiliser le SSID hotspot entre sessions ? sinon delete + retirer les monkeypatches morts de `test_flash_view_model_defaults.py:111-118`) · `WizardState.reuseHotspot` (`wizard_state.py:57,604-612`) · `_PlainRawDevice.SECTOR` (`windows.py:1065`) · scripts bit-rotted : fix signatures `e2e_diag_readback.py:80` + `e2e_probe_write_8mb.py:73`, delete `diag_held_lock_write.py` (prémisse morte) · constante secteur 512 unifiée (`core/constants.py`) · dérivation `%LOCALAPPDATA%` unifiée (`app.py:12-16` vs `windows.py:905-913`) · commentaires périmés (`orchestrator.py:97-107`, `app.py:202-208,300-302`, `windows.py:643-644`) · `build_diagnostic_zip`/`collect_system_info` : brancher un bouton "Exporter diagnostic" (Step 7 ou menu) — la feature est écrite et testée, seule la surface UI manque (quick-win UX) — sinon delete.

**Taille** : M (1 jour). **Dépend** : WP4, WP6.

---

## SÉQUENCEMENT & BUDGET

```
Semaine 1 : WP1 → WP2 → WP3        (fondations vérité + session + démarrage silencieux)
Semaine 2 : WP4 ∥ WP5 → WP6        (sortie propre ∥ quit safety, puis sélection sûre)
Semaine 3 : WP7 → WP8 → WP9        (durcissement, seams CI, purge)
```
~8-10 jours-homme. Quick-wins isolables dès maintenant (1 h chacun, zéro dépendance) : **WP4-1** (`assign` diskpart) et **WP1-1/2** (returncode mountvol).

## PROTOCOLE DE VALIDATION FINALE (definition of done)

1. `python -m pytest` : 112 baseline + ~40 nouveaux, tous verts.
2. **Scénario torture popup** : carte ext4 insérée AVANT launch + marker stale forgé + run NON-élevé → zéro popup, bandeau élévation visible, log explicite.
3. **Scénario captif** : flash complet master → carte visible dans Explorer à la fin SANS réinsertion ; cancel à 50 % → carte exFAT visible ; quit pendant flash → dialogue, cancel propre, carte exFAT visible.
4. **Scénario SSD** : SSD USB 256 GB seul branché → badge suspect, PAS d'auto-select, PAS de démontage, NEXT inactif.
5. **Scénario swap** : carte A auto-sélectionnée → swap B → id suit, NEXT cohérent.
6. **Double instance** : 2e launch → dialogue + exit, automount de l'instance 1 intact.
7. Démarrage : fenêtre/splash visible < 1 s après lancement (chrono), zéro freeze pré-paint.
8. Re-run `verify_golden_image.sh` + flash test réel des images 11-06-2026 (le contexte REPRISE-FLASH-1106 reprend ici).
```
