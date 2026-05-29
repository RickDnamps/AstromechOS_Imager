# AstromechOS Imager

Outil de flashage de cartes SD pour le build R2-D2 du projet **AstromechOS**. Il écrit **deux cartes SD** simultanément (ou en séquence) destinées à deux Raspberry Pi 4B configurés en **Master / Slave**, à partir d'images extraites des Pi4B existants de l'utilisateur.

## Contexte

- **Master Pi 4B (4GB)** — domé, Flask API, dashboard web, PCA9685 (servos dôme), Bluetooth gamepad
- **Slave Pi 4B (2GB)** — corps, listener UART (115200 baud via slip ring, watchdog 500 ms), VESC (drive), audio mpg123, RP2040 LCD
- Logiciel installé sur les Pi → https://github.com/RickDnamps/AstromechOS (Raspberry Pi OS Trixie 64-bit)
- Le imager ne ré-installe pas AstromechOS depuis zéro : il flashe des **images `.img`/`.img.xz`** déjà extraites des deux Pi4B existants

## Base de code

Le dossier `rpi-imager-main/` (gitignoré) est le **code source de référence** de Raspberry Pi Imager (Qt/QML/C++, build via CMake). On s'en inspire mais on ne l'inclut pas dans le repo. Composants pertinents à étudier :

- `src/imagewriter.cpp` / `src/imagewriter.h` — écriture image → device
- `src/downloadextractthread.cpp` / `src/localfileextractthread.cpp` — extraction `.xz`/`.zip` en streaming
- `src/drivelistmodel*` — énumération des disques amovibles
- `src/customization_generator.*` — injection de config (`user-data`, `firstrun.sh`) dans la partition boot
- `src/wizard/`, `src/main.qml` — UI Qt Quick

## Conventions de travail

- Le `.gitignore` exclut `rpi-imager-main/` — ne jamais committer ce dossier
- Remote git : https://github.com/RickDnamps/AstromechOS_Imager (branche `main`)
- L'utilisateur communique en français — répondre en français
- Pas de commits sans demande explicite

## État

Démarrage du projet. Spec en cours de rédaction via brainstorming.
