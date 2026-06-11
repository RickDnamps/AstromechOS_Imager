# AUDIT PHASE 2 — AUTOPSIE TECHNIQUE NARRATIVE (2026-06-11)

> **Marqueur de reprise : `REPRISE-AUDIT-IMAGER-1106`** · Prérequis : `docs/AUDIT_PHASE1_2026-06-11.md` (cartographie + file:line).
> Ce document explique le **POURQUOI** mécanique de chaque bug — la chaîne causale complète, du noyau Windows jusqu'à la ligne de code fautive.
> Phase 3 (plan de refactoring séquencé) : `docs/AUDIT_PHASE3_PLAN_2026-06-11.md`.

---

## AUTOPSIE 1 — Le "Ghost Popup" au démarrage

### 1.1 Le mécanisme Windows sous-jacent (ce que le code combat)

Une Golden Image Pi = partition 1 FAT32 (reconnue par Windows) + partition 2 ext4 (**RAW** pour Windows : aucun driver FS ne la revendique). Quand la carte arrive sur le bus USB :

1. Le **Mount Manager** (mountmgr.sys) reçoit la notification d'arrivée de volume. Si l'automount est ON, il assigne une lettre à CHAQUE volume — y compris l'ext4 — et **persiste le binding volume↔lettre dans `HKLM\SYSTEM\MountedDevices`**. Ce binding survit aux réinsertions.
2. Le popup "Voulez-vous formater ce disque ?" n'est PAS émis par le noyau. Il est émis par **le process qui touche le volume lettré** : tout accès filesystem à `K:` sur un volume RAW échoue en `ERROR_UNRECOGNIZED_VOLUME`, et le hard-error handler du shell (shell32, dans Explorer ou tout process qui charge la machinerie shell) traduit cet échec en dialogue de formatage.
3. **`mountvol /N` (automount OFF) ne bloque que les NOUVELLES arrivées.** Il ne démonte rien d'existant et ne supprime aucune lettre déjà assignée. C'est le fait central que toute la défense actuelle sous-estime.
4. **`SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOOPENFILEERRORBOX)` est PER-PROCESS**, hérité uniquement par les enfants créés après l'appel. Il ne protège jamais Explorer, ni les services.

### 1.2 La chaîne causale n°1 — le marker stale (cause primaire du popup "au démarrage")

C'est le scénario qui colle exactement au symptôme rapporté ("interrompt l'initialisation silencieuse") :

```
Session N : debugging → kill (Task Manager / Ctrl+C / stop debugger)
  └─ aboutToQuit ne fire JAMAIS sur un kill → enable_automount() jamais appelé
  └─ le marker %LOCALAPPDATA%\AstromechOS_Imager\automount_disabled.marker RESTE

Session N+1 (launch) :
  app.py:180  restore_automount_if_crashed() → marker présent → mountvol /E   ← AUTOMOUNT ON
  app.py:181  disable_automount()            → mountvol /N                    ← re-OFF
```

Entre ces deux lignes — et surtout dans les instants qui suivent, car le retour de `/E` déclenche chez MountMgr une **réévaluation des volumes présents sans lettre** — la carte ext4 insérée pendant la session N (dont les lettres avaient été supprimées par `DeleteVolumeMountPointW`) **récupère une lettre**. Le premier scan WMI (T14, premier tick de l'event loop) ou Explorer la touche → popup. Le popup apparaît donc *pendant le splash*, exactement "au démarrage".

**Pourquoi ce design existe** : le marker a été conçu pour réparer la machine de l'opérateur (automount OFF est un réglage system-wide persisté — le laisser OFF après un crash casserait toutes les clés USB de la machine). L'intention est bonne ; le défaut est que le marker **confond "session crashée" et "session active"** (`app.py:224-238` : le mutex existe mais `ERROR_ALREADY_EXISTS` n'est jamais testé) et que la réparation s'exécute **aveuglément avant** la mise en défense, avec la carte déjà insérée.

### 1.3 La chaîne causale n°2 — le poll WMI sonde le volume RAW depuis un process hors de portée

`DriveListModel.refresh()` tourne au premier tick puis toutes les 2 s (`drive_list_model.py:72-76`). Pour chaque disque accepté, `_drive_letters_for()` (`windows.py:33-50`) exécute :

```
ASSOCIATORS OF {Win32_DiskDrive...} WHERE AssocClass=Win32_LogicalDiskToPartition
```

Pour matérialiser les objets `Win32_LogicalDisk`, le provider WMI **accède au volume via sa lettre** (FreeSpace, FileSystem… = appels filesystem réels). Ce code tourne dans **WmiPrvSE.exe**, un host de service DCOM qui n'est PAS un enfant de l'Imager : le `SetErrorMode` posé à `app.py:147` ne s'y applique pas. Si une carte ext4 lettrée est présente (chaîne n°1, ou carte insérée avant le tout premier launch), **chaque cycle de 2 s est une occasion de re-déclencher le popup**. C'est pour ça que le popup peut revenir après avoir été fermé.

**Pourquoi ce design existe** : WMI ASSOCIATORS est la façon canonique d'obtenir disque→partitions→lettres en une requête, et le scan ne s'attendait pas à coexister avec des volumes RAW lettrés — l'hypothèse implicite était "automount OFF ⇒ jamais de lettre", fausse pour les cartes pré-insérées (§1.1.3) et après un `/E` (§1.2).

### 1.4 La chaîne causale n°3 — la défense peut être une fiction (élévation)

`_run_mountvol` (`windows.py:916-927`) fait `subprocess.run(...)` **sans `check` et sans lire `returncode`** : il retourne `True` dès que le process a pu être lancé. Or `mountvol /N` exige l'élévation. Conséquence en run non-élevé (dev `python -m`, manifest cassé, UAC refusé) :

- `mountvol /N` échoue (rc≠0) → l'app log "automount disabled for the flash" (`windows.py:943`) → **mensonge**.
- Le marker est écrit → le prochain launch fera un `/E` "réparateur" sur un réglage… qui n'a jamais changé.
- Toute la défense anti-popup de la session repose alors sur rien. stdout/stderr de mountvol sont capturés puis **jetés** : zéro trace forensique dans `startup.log`.

La docstring (`windows.py:934-935`) promet "Returns True only when mountvol /N succeeded" — le code ne tient pas cette promesse. Symétriquement, `enable_automount` (`:947-955`) **supprime le marker même si `/E` a échoué** et retourne `True` inconditionnellement : un restore raté détruit la seule trace qui aurait permis de réparer plus tard → machine avec automount OFF pour toujours, silencieusement.

### 1.5 Pourquoi l'initialisation est "interrompue" (le ressenti opérateur)

Deux facteurs se cumulent : (a) le popup vole le focus pendant le splash (il vient d'Explorer/WmiPrvSE, pas de notre process — il s'affiche par-dessus) ; (b) le tout premier `refresh()` WMI est **synchrone sur le main thread avant le premier paint** (`singleShot(0)` à `app.py:353` fire au premier tick, pas "après le splash" comme le prétend le commentaire `app.py:300-302`) — si WMI bloque (il peut prendre des secondes face à un volume RAW), la fenêtre n'est même pas encore affichée. Et avant tout ça, les `mountvol` du launch (`app.py:180-181`) bloquent le main thread jusqu'à 30-45 s de timeout cumulé dans le pire cas, AVANT la création de `QGuiApplication`.

### 1.6 Verdict — pourquoi les fixes c6d2497/69b836b n'ont pas suffi

Ils ont fermé les bonnes fenêtres (insertion APRÈS launch ; lettres du disque SÉLECTIONNÉ) mais ont laissé ouvertes : la fenêtre `/E`→`/N` du marker stale (la plus probable en phase de debugging intensif, où on kill l'app sans arrêt), les lettres des cartes pré-insérées NON sélectionnées, le poll WMI qui touche ces lettres depuis un process non protégé, et l'absence totale de vérification du succès de `mountvol`. **Le popup n'a jamais été un bug unique : c'est un système à 4 entrées dont 2 ont été fermées.**

---

## AUTOPSIE 2 — Le lecteur captif dans l'Explorateur

### 2.1 Découverte centrale : ce n'est PAS une fuite de handle

L'hypothèse intuitive ("un handle FSCTL_LOCK_VOLUME reste ouvert") est **réfutée par le code** : depuis le revert du held-lock, `lock_and_dismount` fait lock→dismount→unlock→**close** par volume (`windows.py:276-296`) et retourne toujours `[]` (`:339`). La boucle `locked_handles` de l'orchestrator (`orchestrator.py:330-339`) est un no-op permanent. L'inventaire complet des `CreateFileW` (Phase 1 §2-B tableau) montre des fermetures garanties sur succès/échec/cancel via double-`finally` (`orchestrator.py:246-250` + `:325-329`), idempotence pinnée par `test_handle_idempotency.py`.

**Le lecteur captif est l'état final que le code CONSTRUIT délibérément, puis n'inverse jamais.**

### 2.2 La chaîne causale — l'entonnoir à sens unique

Le cycle de vie d'une lettre dans cette app ne connaît que des soustractions :

```
Step 4 (sélection, zéro clic — cf. Autopsie 3)
  └─ _release_letters_async → force_unmount_letter → DeleteVolumeMountPointW
       (la lettre ET son binding MountedDevices sont détruits)
Flash (WRITE)
  └─ lock_and_dismount → re-DeleteVolumeMountPointW (merge live+scan)
  └─ _wait_for_unmount → re-force_unmount_letter sur tout survivant
Succès
  └─ finalize_eject (IOCTL_STORAGE_EJECT_MEDIA) → ÉCHOUE sur la plupart des
     bridges SD-USB (admis par la docstring windows.py:866-869) → return False
  └─ ... et c'est TOUT. Aucun attach de lettre, aucun SetVolumeMountPointW,
     aucun IOCTL_DISK_UPDATE_PROPERTIES. (Les outils existent : windows.py:636-710,
     :741-743 — ZÉRO caller.)
Quit
  └─ enable_automount (mountvol /E) → ne vaut que pour les arrivées FUTURES :
     ne ré-assigne JAMAIS une lettre aux volumes déjà présents.
```

Résultat : la carte fraîchement flashée (FAT32 parfaitement valide !) est **présente, saine, et letterless** — invisible ou en icône morte — jusqu'à réinsertion physique. L'opérateur voit un lecteur "captif". Le système n'est pas verrouillé : il est *orphelin*.

### 2.3 Le cas aggravé — cancel/échec : la recovery se saborde elle-même

`restore_readable_exfat` (`windows.py:752-780`) reformate la carte en exFAT pour que "l'opérateur voie un disque utilisable". Son script diskpart **omet volontairement `assign`**, avec ce raisonnement documenté : "Windows auto-mounts the removable exFAT volume and picks a free letter on its own" (`:776-780`). Ce raisonnement était vrai quand l'automount n'était coupé que pendant le flash (design pré-c6d2497). Depuis que l'automount est OFF **pour toute la session** (`app.py:180-182`, jamais ré-activé per-card par design `orchestrator.py:359-364`), la prémisse est morte : la carte est bien reformatée… et n'obtient **aucune lettre**. L'opérateur annule un flash, la carte "disparaît", il conclut qu'elle est brickée. **Deux fixes corrects pris isolément (automount session-long + exFAT-sans-assign) se contredisent mutuellement** — un défaut d'intégration, pas de conception locale.

### 2.4 L'icône fantôme — le shell n'est jamais prévenu

`DeleteVolumeMountPointW` détruit le binding mais **ne notifie pas Explorer**, qui rend son cache. La notification (`SHChangeNotify(SHCNE_MEDIAREMOVED/SHCNE_DRIVEREMOVED)`) existe dans le code — `native_shell_quiet.lock_and_quiet` — mais : (a) elle n'est appelée QUE dans `lock_and_dismount` (`windows.py:325-332`), jamais par le release Step-4 ni par `force_unmount_letter` ; (b) elle dépend de `astro_flash.dll`, et **dégrade en no-op silencieux si la DLL est absente** (`native_shell_quiet.py:50-77`). Donc entre la sélection Step-4 et le flash — ou pour toujours si la DLL manque — Explorer affiche un `K:` mort qui produit une erreur au clic : c'est la perception "captif PENDANT le run".

À cela s'ajoute le seul "verrouillage" réel et légitime : pendant la phase customize, **deux handles `GENERIC_READ|WRITE`** sur le même `\\.\PhysicalDriveN` coexistent (streaming NO_BUFFERING encore ouvert + handle plain de `RawFatBootPartition`, `raw_fat_partition.py:63`) — légal, voulu, mais tout outil tiers dira "périphérique utilisé" pendant le flash.

### 2.5 Le scénario destructeur — quit en plein flash (F4)

Aucun `onClosing` QML, rien ne connecte `aboutToQuit`→`cancel()`. Si l'opérateur ferme la fenêtre pendant l'écriture : (a) `aboutToQuit` exécute `enable_automount()` (`app.py:212`) **pendant que le writer streame** → Windows peut monter/sonder la carte à moitié écrite → popup format en plein flash + marker supprimé (le filet de sécurité disparaît) ; (b) le process se termine avec le QThread writer vivant → écriture tuée mi-stream → carte RAW, et `restore_readable_exfat` ne tourne jamais → carte réellement "brickée" jusqu'à reformatage manuel. **C'est le seul chemin qui produit une carte véritablement captive ET corrompue.**

---

## AUTOPSIE 3 — L'auto-détection : une politesse devenue arme

### 3.1 Le filtre laisse passer le pire candidat possible

`enumerate_removable_drives` (`windows.py:75-134`) accepte si `InterfaceType=="USB"` **OU** "removable" dans MediaType (`:92-96`). Le OR est un choix documenté (`:78-83`) : certains lecteurs SD derrière des bridges SCSI se déclarent `Fixed` — un AND les rejetterait. Effet secondaire non pesé : **tout SSD USB se déclare `InterfaceType=USB` + `MediaType=Fixed`** et passe la porte 1. La porte taille : `_MAX_SD_BYTES = 256 GiB` (`windows.py:20`) = 274 877 906 944 octets ; un SSD "256 GB" marketing = ~256 060 514 304 octets **décimaux** → passe sous le cap avec 18 Go de marge. Le commentaire dit "no R2 build needs > 256 GB" — la limite a été pensée comme un plafond de plausibilité SD, pas comme une frontière SSD/SD, et l'unité GiB-vs-GB fait le reste. Aucune des trois protections qui manquent n'existe : exclusion `MediaType=Fixed` (sauf confirmation), exclusion du **disque hébergeant `masterImagePath`/`slaveImagePath`** (le SSD-source de l'opérateur !), heuristique BusType/RemovableMedia via IOCTL_STORAGE_QUERY_PROPERTY.

### 3.2 La sélection zéro-clic transforme l'énumération en action destructive

`_autoSelectImposed()` (`Step4Role.qml:67-73`) s'exécute à `Component.onCompleted` + `onImposedRoleChanged` + `onDriveCountChanged` : dès que `driveCount==1`, le seul disque est assigné au rôle imposé **sans aucun clic** (`setMasterDriveId(firstDriveId)`, `:54-62`). Or ce setter a un **effet de bord système** : il fire `_release_letters_async` (`wizard_state.py:437,444`) → `force_unmount_letter` → les lettres du disque sont DÉTRUITES. La chaîne complète du pire cas : *SSD-source seul branché → auto-sélectionné → démonté → l'archive d'images disparaît d'Explorer → NEXT actif → un clic WRITE de l'écraser.* Les deux garde-fous résiduels sont accidentels : le banner "MULTIPLE SD CARDS" (exige ≥2 disques) et le fait que démonter le SSD-source ferait échouer la lecture du hash. **Principe violé : une opération destructive (même réversible par réinsertion) ne doit jamais découler d'une simple énumération passive.** L'auto-select a été conçu pour l'UX ("l'opérateur n'a qu'une carte, pourquoi le faire cliquer ?") en oubliant que la sélection n'est plus une simple écriture d'état depuis 69b836b — elle porte un effet de bord matériel.

### 3.3 Le trou stale-id au swap de carte

La garde de `_autoSelectImposed` est `currentRole !== imposedRole` (`Step4Role.qml:68`) — une garde sur le **rôle**, pas sur le **disque**. Séquence : carte A auto-sélectionnée (`masterDriveId=A`, `currentRole="master"`) → l'opérateur retire A, insère B → `driveCount` repasse à 1, `_autoSelectImposed` re-run, mais `currentRole==="master"` déjà → **no-op : `masterDriveId` vaut toujours A**. Aucun handler `onFirstDriveIdChanged` n'existe. L'UI affiche B (bindings live `:49-52`) pendant que l'état pointe A ; NEXT reste actif (`:422-424` ne teste que `hasOneCard`). Au WRITE : si Windows a recyclé le même numéro de disque (même slot de lecteur = cas courant) → B est flashée "par chance" ; sinon `_build_flash_job` échoue proprement "drive not found" (`flash_view_model.py:860-865`) — sûr mais incompréhensible pour l'opérateur. Le filtre d'éligibilité borne le rayon d'explosion (jamais le disque système), mais l'invariant attendu — *l'id sélectionné désigne le disque affiché* — n'est pas tenu.

### 3.4 Contre-exemple : le flux pair Master→Slave est, lui, bien conçu

`resetForNextCycle()` (`wizard_state.py:552-566`) clear les deux drive-ids à −1 (sans déclencher le release, garde `:462`), `endSession()` (`:527-550`) wipe tout + re-mint le SSID hotspot ; le tout pinné par `test_wizard_state_sequential.py`. La leçon : quand l'équipe a pensé "cycle de vie de l'état", elle l'a bien fait — les défauts 3.1-3.3 sont précisément les endroits où l'état rencontre le **matériel** sans contrat explicite.

---

## SYNTHÈSE — Les 5 causes racines systémiques (le pourquoi du pourquoi)

Chaque bug individuel ci-dessus est un symptôme d'un des patterns suivants. La Phase 3 traite les patterns, pas seulement les symptômes :

1. **La frontière win32 ment** : les retours sont ignorés (`_run_mountvol` rc, `disable_automount` aux 2 call sites, `enable_automount` inconditionnel) et les erreurs avalées par des `except Exception: pass` en cascade (`app.py:148,159,182,213,237`). Les défenses deviennent des **croyances**, pas des faits. Un système de sécurité qui ne sait pas s'il est armé n'est pas un système de sécurité.
2. **Angle mort des frontières de process** : `SetErrorMode` est supposé protéger "le système" alors qu'il est per-process ; or les acteurs qui POPent (Explorer, WmiPrvSE) sont hors process. La seule vraie défense est de **ne pas laisser exister de volume RAW lettré**, pas de supprimer les dialogues.
3. **Cycle de vie asymétrique** : chaque fix a ajouté une soustraction (lettres supprimées, automount off) sans jamais ajouter la restauration symétrique. L'entropie converge vers "lecteur captif". Les outils de restauration existent dans le code (`attach_letter_to_unmounted_volume`, `update_disk_properties`) avec zéro caller — l'intention y était, l'intégration jamais.
4. **État global machine géré par un process sans modèle de session** : l'automount est system-wide, le marker est per-user, le mutex n'est pas testé, deux instances se marchent dessus. Il manque un objet unique propriétaire du couple {automount, marker} avec un protocole clair (acquire/release/repair).
5. **Le main thread fait de l'I/O système** (mountvol bloquants pré-Qt, WMI synchrone pré-paint) et **les tests n'ont pas de seam** (`build_app` exécute les vrais mountvol sous pytest) : les défauts 1-4 sont invisibles en CI et coûteux à reproduire.

→ **Plan de remédiation complet, séquencé et testable : `docs/AUDIT_PHASE3_PLAN_2026-06-11.md`.**
