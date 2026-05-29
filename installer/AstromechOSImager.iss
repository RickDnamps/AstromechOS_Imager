; AstromechOS Imager — Inno Setup script
;
; Build:  iscc installer\AstromechOSImager.iss
; Output: dist\AstromechOS_Imager-Setup-{version}.exe
;
; Requires Inno Setup 6.2+ : https://jrsoftware.org/isinfo.php
; The PyInstaller onedir bundle (dist\AstromechOS Imager\) must exist
; before running iscc — see BUILD_INSTRUCTIONS.md.

#define AppName        "AstromechOS Imager"
#define AppVersion     "0.1.0"
#define AppPublisher   "AstromechOS Project"
#define AppURL         "https://github.com/RickDnamps/AstromechOS_Imager"
#define AppExeName     "AstromechOS Imager.exe"
#define BundleSource   "..\dist\AstromechOS Imager"
#define IconSource     "..\images\AstromechOS_Imager.ico"

[Setup]
AppId={{4F8C4E2E-6A1B-4A4F-8C2E-2D9E7A1B3E5C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir=..\dist
OutputBaseFilename=AstromechOS_Imager-Setup-{#AppVersion}
SetupIconFile={#IconSource}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The app's PyInstaller manifest already requires admin; the installer
; needs admin too to write under Program Files.
PrivilegesRequired=admin
WizardStyle=modern
DisableDirPage=auto
DisableReadyPage=no
ShowLanguageDialog=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french";  MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Pull the entire onedir bundle. Recurse subdirs. Skip Inno's leftover stuff.
Source: "{#BundleSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";                Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";          Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runascurrentuser

[UninstallDelete]
; Wipe the per-user startup log dir on uninstall.
Type: filesandordirs; Name: "{localappdata}\AstromechOS_Imager"
