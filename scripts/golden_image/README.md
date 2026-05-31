# `scripts/golden_image/` — Build Golden Images from existing Pis

Scripts réutilisables pour extraire les Golden Images consommées par l'AstroMechOS_Imager.

**Pour la doc complète + lessons learned : [`docs/GOLDEN_IMAGE_BUILD.md`](../../docs/GOLDEN_IMAGE_BUILD.md).**

---

## Files

| Script | Tourne où | Rôle |
|---|---|---|
| `pi_cleanup.sh` | Sur le Pi (master ou slave), en root | Stop les services, vide les caches/logs/tmp, mount le SSD |
| `wsl_pishrink.sh` | Dans WSL2 Debian sur le PC, en root | Pishrink le .img avec `-a -s -z`, output `.img.gz` |
| `finalize_image.ps1` | PowerShell sur le PC | Copy K: → J:\R2-D2_Build\images\ avec nom canonique + SHA256 + sidecar |

---

## Quick reference

### Master Golden

```bash
# Sur PC, SSH au master :
ssh artoo@192.168.2.104
sudo bash /home/artoo/astromechos/scripts/golden_image/pi_cleanup.sh master

# Paste le dd indiqué en fin de cleanup
echo deetoo | sudo -S sh -c 'sync; dd if=/dev/mmcblk0 of=/mnt/ssd/master_golden.img bs=4M status=progress conv=fdatasync; sync; ls -la /mnt/ssd/master_golden.img'

# Unmount + exit SSH
echo deetoo | sudo -S sh -c 'sync; umount /mnt/ssd && echo SSD_UNMOUNTED_CLEAN'
exit

# Physique : SSD master Pi → PC

# Sur PC, PowerShell :
wsl --shutdown
wsl -d Debian -u root -- bash /mnt/j/R2-D2_Build/AstroMechOS_Imager/scripts/golden_image/wsl_pishrink.sh master_golden.img

# Copy + SHA256 + sidecar (un seul script)
powershell -ExecutionPolicy Bypass -File `
  J:\R2-D2_Build\AstroMechOS_Imager\scripts\golden_image\finalize_image.ps1 -Role master
```

### Slave Golden

Pareil mais :
- SSH via ProxyJump : `ssh -J artoo@192.168.2.104 artoo@192.168.4.171`
- `pi_cleanup.sh slave`
- `dd ... of=/mnt/ssd/slave_golden.img ...`
- `wsl_pishrink.sh slave_golden.img`
- Copy en `AstromechOS_Slave_<date>.img.gz`

---

## Pourquoi `-s` dans pishrink ?

L'AstroMechOS_Imager injecte le **resize natif Pi OS** (`init=/usr/lib/raspberrypi-sys-mod/init_resize.sh`) dans cmdline.txt au cold-flash via `astromechos_imager/core/rootfs_personalizer.py`. Sans `-s`, pishrink ajouterait son propre `/etc/rc.local` qui ferait un resize doublon (et pollue la rootfs avec un fichier qui ne servirait jamais sur Debian Trixie où `rc-local.service` est disabled par défaut).

**Toujours `-a -s -z` pour produire un Golden propre.**

---

## Pourquoi pishrink sur PC et pas sur Pi ?

- Slave Pi a 2 GB de RAM. `e2fsck + resize2fs + pigz parallèle` dépasse facilement 2 GB → OOM thrashing.
- Master Pi a 4 GB mais sa stack Flask + drivers tourne en permanence → marge insuffisante.
- WSL2 sur PC a accès à toute la RAM du host (16+ GB typique) → zéro risque d'OOM.

---

## Pourquoi USB 3.0 SSD et pas USB-SD adapter ?

- Adapter USB-SD typique = USB 2.0 = 30 MB/s = **4 heures pour un SD 128 GB**.
- SSD SATA externe + adapter USB 3.0 SuperSpeed = 40-90 MB/s SD read sustained = **50 min pour le même SD**.
- Le SSD reste branché au Pi pendant tout le dd (zéro déplacement physique en cours), puis se déplace au PC pour le pishrink.
