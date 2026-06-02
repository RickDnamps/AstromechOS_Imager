# Golden Image Build Workflow

Comment extraire les **Golden Images** (`master_golden.img.gz` + `slave_golden.img.gz`) à partir des deux Raspberry Pi 4B existants du projet **AstromechOS**, pour usage avec l'**AstroMechOS_Imager**.

> **Pourquoi ce doc** : ce workflow a été défini empiriquement la nuit du 30→31 mai 2026 après plusieurs tentatives ratées. Documenter pour ne plus refaire les erreurs (chkdsk sur FAT32 Pi OS, pishrink sur Pi 2GB qui OOM, etc.). Toutes les "lessons learned" sont en bas du doc.

---

## 1. Objectif

Produire deux fichiers compressés flashables :

| Fichier | Taille typique | Description |
|---|---|---|
| `AstromechOS_Master_<date>.img.gz` | ~1.3 GB | Snapshot du master Pi 4B 4GB |
| `AstromechOS_Slave_<date>.img.gz` | ~1.3 GB | Snapshot du slave Pi 4B 2GB |
| `*.img.gz.sha256` | 104 bytes | Sidecar checksum (format `sha256sum`) |

Ces fichiers sont consommés par l'**AstroMechOS_Imager** qui fait :
- Cold rootfs surgery (rename UID-1000 user, change role marker, regen secrets)
- Injection du resize trigger natif dans `cmdline.txt` (token `resize` + `ds=nocloud;i=…`)
- Flash vers les nouvelles SD du fleet

---

## 2. Architecture du workflow

```
                              ╔══════════════════════╗
                              ║    PC dev (Win11)    ║
                              ║  WSL2 Debian Trixie  ║
                              ╚══════════╤═══════════╝
                                         │ SSH (192.168.2.x WiFi)
                                         │ + ProxyJump pour slave
                                         ▼
                  ┌──────────────────┴──────────────────┐
                  │                                     │
        ┌─────────▼──────────┐                ┌─────────▼──────────┐
        │  Master Pi 4B 4GB  │   hotspot      │  Slave Pi 4B 2GB   │
        │ 192.168.2.104 wlan1│ ◄────────────► │ 192.168.4.171 wlan │
        │ 192.168.4.1   wlan0│   192.168.4.x  │   (hotspot client) │
        └─────────┬──────────┘                └─────────┬──────────┘
                  │ USB 3.0                             │ USB 3.0
                  ▼                                     ▼
        ┌─────────────────────────────────────────────────────┐
        │  USB 3.0 SSD (256 GB exFAT, JMicron JMS578 typical) │
        │  /mnt/ssd  — destination du dd raw                  │
        └─────────────────────────────────────────────────────┘

Le SSD se déplace **physiquement** entre les Pis et le PC.
```

**Pourquoi pas du SSH live-dd direct PC → Pi ?** Tested. WiFi 5GHz bottleneck à ~50-80 MB/s, et le master mange du CPU/RAM avec sa stack Flask. **USB 3.0 SSD local au Pi = 40 MB/s sustained stable** (bottleneck = SD card read), pas de network jitter, pas de bottleneck WiFi.

---

## 3. Prérequis

- **SSD externe USB 3.0** ≥ 128 GB en exFAT (Windows natif). Le master Pi capture ~120 GB raw, le slave ~60 GB raw → besoin de ~200 GB pour avoir les deux + travail temporaire.
- **Adaptateur SATA-USB 3.0** (le SuperSpeed bus est critique — USB 2.0 limite à 30 MB/s = 4h pour master au lieu de 50 min)
- **WSL2 Debian** installé sur le PC (Debian Trixie 13.x recommandé, kernel ≥ 6.6)
- **Master Pi opérationnel et joignable** sur le réseau home WiFi (192.168.2.104)
- **Slave Pi opérationnel** sur le hotspot du master (192.168.4.171, atteignable seulement via master comme jump host)

---

## 4. Workflow Master (~60 min total)

### 4.1 Cleanup + mount SSD côté master (~30 sec)

Depuis le PC, en SSH sur le master via paramiko OU en SSH manuel (`ssh artoo@192.168.2.104`) :

```bash
sudo bash scripts/golden_image/pi_cleanup.sh master
```

Ce script (run en root) :
- Stop `astromech-master.service` + `avahi-daemon` + `bluetooth` + `ModemManager` (~400 MB RAM libérés)
- Tronque tous les `/var/log/*.log`
- Supprime les logs rotated (`.gz`, `.1`, `.old`)
- Vacuum `journalctl` à 1 MB max
- Vide le cache APT
- Vide `/tmp/*` et `/var/tmp/*`
- Vide `~/.bash_history`
- Monte le SSD à `/mnt/ssd`
- `sync` + drop kernel caches

### 4.2 dd master → SSD (~50 min)

SSH au master, paste :

```bash
echo deetoo | sudo -S sh -c 'sync; dd if=/dev/mmcblk0 of=/mnt/ssd/master_golden.img bs=4M status=progress conv=fdatasync; sync; ls -la /mnt/ssd/master_golden.img'
```

Throughput attendu : **~40 MB/s sustained** (UHS-I A1 typique). Pour 117.8 GB → ~50 min.

> ⚠️ **NE PAS** lancer pishrink sur le master Pi pendant que `astromech-master.service` tournerait. La combo `e2fsck + resize2fs + pigz parallèle + Flask stack` saturait les 4 GB de RAM → OOM thrashing → hang plusieurs heures. Pishrink se fait **toujours dans WSL2** sur le PC.

### 4.3 Unmount SSD côté master

```bash
echo deetoo | sudo -S sh -c 'sync; umount /mnt/ssd && echo SSD_UNMOUNTED_CLEAN'
```

Tu dois voir `SSD_UNMOUNTED_CLEAN`. Si `UMOUNT_FAILED`, vérifier qu'aucun process ne tient `/mnt/ssd` (`sudo lsof +D /mnt/ssd`).

### 4.4 Déplacement physique du SSD vers PC

1. Unplug SSD du port USB master Pi
2. Plug au PC en USB 3.0
3. Windows monte automatiquement comme drive **K:** (~5 sec)

### 4.5 Pishrink + compression dans WSL2 (~5-10 min)

Dans PowerShell sur le PC :

```powershell
wsl --shutdown
wsl -d Debian -u root -- bash /mnt/j/R2-D2_Build/AstroMechOS_Imager/scripts/golden_image/wsl_pishrink.sh master_golden.img
```

Le `wsl --shutdown` est nécessaire si le SSD a été plugged après le boot de WSL — sinon `/mnt/k` n'existe pas. Au prochain démarrage WSL re-scanne les drives Windows.

Le script (run en root WSL) :
- Auto-monte K: en drvfs si pas mounté
- Auto-installe `pigz` + `pishrink` (depuis GitHub Drewsif/PiShrink/master) si manquants
- Run `pishrink -a -s -z <img>` :
  - `-a` = compression parallèle pigz (utilise tous les cores du PC)
  - `-s` = **SKIP autoexpand setup** (pas de `/etc/rc.local` injection — l'Imager gère le resize via cmdline.txt)
  - `-z` = gzip output → `.img.gz`

Output : `K:\master_golden.img.gz` (~1.3 GB).

### 4.6 Copy + SHA256 + sidecar

Script automatique (recommandé) :
```powershell
powershell -ExecutionPolicy Bypass -File `
  J:\R2-D2_Build\AstroMechOS_Imager\scripts\golden_image\finalize_image.ps1 `
  -Role master
```

Le script :
- Copie `K:\master_golden.img.gz` → `J:\R2-D2_Build\images\AstromechOS_Master_<DD-MM-YYYY>.img.gz`
- Compute SHA256 via `Get-FileHash` (~7s pour 1.3 GB sur NVMe)
- Écrit le sidecar `.sha256` au format standard `<hash>  <basename>`

Équivalent manuel si tu préfères contrôler :
```powershell
Copy-Item K:\master_golden.img.gz J:\R2-D2_Build\images\AstromechOS_Master_<date>.img.gz
```

Puis dans Git Bash :
```bash
cd "J:/R2-D2_Build/images" && sha256sum "AstromechOS_Master_<date>.img.gz" | tee "AstromechOS_Master_<date>.img.gz.sha256"
```

Le sidecar `.sha256` suit le format standard `sha256sum` : `<hash>  <filename>` (deux espaces).

---

## 5. Workflow Slave (~35 min total)

**Différences vs master** :
- Slave atteignable uniquement via SSH ProxyJump (`-J artoo@192.168.2.104`)
- SD plus petite (typique 64 GB vs 128 GB du master) → dd ~25 min au lieu de 50 min
- **RAM 2 GB seulement** — pishrink sur slave = mort assurée. Encore plus impératif de faire pishrink sur PC.

### 5.1 Cleanup slave via SSH chain

Depuis le PC en paramiko (via le master jump host) :
```bash
ssh artoo@192.168.4.171 "sudo bash scripts/golden_image/pi_cleanup.sh slave"
```

(L'utilisateur peut aussi SSH chain manuellement : `ssh -J artoo@192.168.2.104 artoo@192.168.4.171` puis lancer le cleanup.)

### 5.2 dd slave → SSD

En SSH chain :
```powershell
ssh -J artoo@192.168.2.104 artoo@192.168.4.171
```
puis sur slave :
```bash
echo deetoo | sudo -S sh -c 'sync; dd if=/dev/mmcblk0 of=/mnt/ssd/slave_golden.img bs=4M status=progress conv=fdatasync; sync; ls -la /mnt/ssd/slave_golden.img'
```

~25 min.

### 5.3 Unmount, déplacement physique, pishrink, copy + sha256

Identique au master mais avec `slave_golden.img` au lieu de `master_golden.img` :

```powershell
wsl --shutdown
wsl -d Debian -u root -- bash /mnt/j/R2-D2_Build/AstroMechOS_Imager/scripts/golden_image/wsl_pishrink.sh slave_golden.img
Copy-Item K:\slave_golden.img.gz J:\R2-D2_Build\images\AstromechOS_Slave_31-05-2026.img.gz
```

---

## 6. Le flag `-s` est critique

PiShrink par défaut crée `/etc/rc.local` dans la rootfs qui contient un script `do_expand_rootfs()` qui :
1. Essaie `raspi-config --expand-rootfs` (peut être absent sur Pi OS Lite)
2. Fallback `fdisk` + `resize2fs` + reboot
3. Restore `/etc/rc.local.bak`

**Mais l'AstroMechOS_Imager fait sa propre injection** via `astromechos_imager/core/cloud_init_generator.py` — la méthode native Trixie observée sur une vraie carte officielle rpi-imager :
```python
# build_cmdline() ajoute ces deux tokens dans /cmdline.txt :
"resize"                       # → hook initramfs resize_early : resize la PARTITION (parted)
"ds=nocloud;i=rpi-imager-<ms>" # → active cloud-init : cc_resizefs resize le FILESYSTEM
```

Il patche `/cmdline.txt` (sur la FAT32 boot). Au boot du Pi flashé : le hook initramfs `scripts/local-premount/resize_early` voit ` resize` dans `/proc/cmdline` et agrandit la partition, puis cloud-init (`cc_resizefs`) agrandit l'ext4. **Aucun `init=`** (le vieux hack PID 1 qui bricke si le chemin est faux est abandonné). Un token `resize` inconnu est simplement ignoré par le kernel → zéro risque de panic.

**Conflit potentiel** si on a les deux mécanismes :
- Heureusement, sur Debian Trixie moderne, `rc-local.service` est **disabled** par défaut → le `/etc/rc.local` de pishrink ne s'exécuterait pas de toute façon
- MAIS il pollue la rootfs avec un fichier inutile

**Solution propre** : `pishrink -s` = skip autoexpand = pas de rc.local injecté = rootfs reste 100% native Pi OS.

---

## 7. Lessons learned (à éviter)

| Erreur | Conséquence | Comment éviter |
|---|---|---|
| `chkdsk K: /F` sur FAT32 d'une Pi OS SD | Tronque les fichiers de boot (`start4.elf`, `kernel8.img`, `cmdline.txt`, ...) → Pi ne boote plus | **Ne JAMAIS chkdsk** une FAT32 Pi OS. Les "phantom dirs" `USUSUSUS.usu` sont des résidus inoffensifs, Pi OS s'en fout |
| Pishrink lancé sur le Pi avec service tournant | OOM thrashing → hang plusieurs heures | Toujours **pishrink dans WSL2** sur le PC |
| dd en streaming SSH via WiFi | ~50-80 MB/s WiFi 5GHz + jitter + OS du Pi sous charge = imprévisible | **USB 3.0 SSD local au Pi** → 40 MB/s stable |
| USB-SD adapter en USB 2.0 | 30 MB/s max = 4h pour 128 GB | USB 3.0 SuperSpeed pour le SSD |
| pishrink avec `-p` flag | Pas supporté par cette version → affiche l'aide et exit silencieusement avec rc=0 | Lire la sortie réelle de pishrink, pas juste le rc final |
| pishrink sans `-s` | Crée `/etc/rc.local` inutile dans la rootfs | **Toujours utiliser `-s`** car l'Imager gère le resize |

---

## 8. Récupération en cas de FAT32 morte

Si une FAT32 de boot Pi OS est détruite (chkdsk accidentel, par exemple) :

1. **Le rootfs ext4 (partition 2) est intact** — Windows ne peut pas y toucher, seul Linux peut.
2. **Les fichiers de boot Pi OS sont génériques** (identiques sur tous les Pi 4 avec le même Pi OS) — copiables depuis n'importe quelle SD Pi OS Trixie intacte.
3. **Le `cmdline.txt` est Pi-spécifique** (contient `PARTUUID` du rootfs). Récupérable depuis FOUND.000 si chkdsk a laissé des CHK files.
4. **astromech_role.json** : Pi-spécifique, à réécrire manuellement (`{"role": "master"|"slave", "project": "AstromechOS", "version": "2.0"}`).

Procédure résumée :
- Backup la FAT32 d'une SD intacte (slave par exemple)
- Format quick la FAT32 cassée
- Copy les fichiers générics depuis le backup
- Réécrit cmdline.txt + astromech_role.json avec les valeurs Pi-spécifiques
- Re-insert dans le Pi, ça boote sur le rootfs ext4 inchangé

(Voir scripts `.tmp_step1_backup_slave_fat32.ps1` et `.tmp_step2_restore_to_master.ps1` dans `AstromechOS/` qui ont fait cette opération avec succès le 30 mai 2026.)

---

## 9. Quick reference card

```
MASTER GOLDEN:
  1. ssh artoo@192.168.2.104                    # SSH master
  2. sudo bash pi_cleanup.sh master              # stop services + mount SSD
  3. echo deetoo | sudo -S dd if=/dev/mmcblk0 of=/mnt/ssd/master_golden.img bs=4M status=progress conv=fdatasync
  4. echo deetoo | sudo -S umount /mnt/ssd
  5. exit                                        # quit SSH
  6. <physical: SSD master Pi → PC>
  7. wsl --shutdown                              # PowerShell
  8. wsl -d Debian -u root -- bash wsl_pishrink.sh master_golden.img
  9. Copy-Item K:\master_golden.img.gz J:\R2-D2_Build\images\AstromechOS_Master_<date>.img.gz
  10. sha256sum AstromechOS_Master_<date>.img.gz > AstromechOS_Master_<date>.img.gz.sha256

SLAVE GOLDEN: same pattern, ssh -J jump host, slave_golden.img
```
