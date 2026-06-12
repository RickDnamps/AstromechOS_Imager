; AstromechOS Imager — Inno Setup script
;
; Build:  iscc installer\AstromechOSImager.iss
; Output: dist\AstromechOS_Imager-Setup-{version}.exe
;
; Requires Inno Setup 6.3+ (uses ArchitecturesAllowed=x64compatible which
; landed in 6.3.0). Install via: choco install innosetup OR
; https://jrsoftware.org/isinfo.php
;
; The PyInstaller onedir bundle (dist\AstromechOS Imager\) must exist
; before running iscc — see BUILD_INSTRUCTIONS.md.

#define AppName        "AstromechOS Imager"
; Audit Low #50: when bumping the project version, update BOTH of:
;   1. pyproject.toml          → project.version (Python package version)
;   2. astromechos_imager/__init__.py → __version__ (runtime + UI footer)
;   3. THIS LINE               → AppVersion (installer + Inno SetupMutex)
; A future improvement would auto-derive this from pyproject.toml via a
; build-time generated `version.iss` include; deferred to keep iscc
; invocable as a single command.
#define AppVersion     "0.2.2"
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

; Audit High #21: AppMutex prevents the installer from running while the
; flashing app is in the middle of a destructive write. The app creates a
; matching named mutex at startup in app.py.
AppMutex=Global\AstromechOS_Imager_AppMutex
SetupMutex=AstromechOS_Imager_Setup_{#AppVersion}

; Audit Medium #40: MinVersion gates install on Win10 1809 (build 17763),
; matching PySide6 6.7's documented Win10 floor. Without this, the
; installer accepts Win7/8/8.1 then the app crashes in pywin32 / WMI
; with no clear cause.
MinVersion=10.0.17763

; Audit Medium #39: code-signing hook is OPT-IN to keep the default
; `iscc installer\AstromechOSImager.iss` invocation working with no
; signing infrastructure. To produce a signed installer:
;
;   1. In Inno Setup IDE: Tools → Configure Sign Tools… and register a
;      tool named `mysigntool` whose command line is:
;         "C:\Program Files (x86)\Windows Kits\10\bin\<sdk>\x64\signtool.exe" \
;             sign /f $p /p $q /tr http://timestamp.digicert.com \
;             /td sha256 /fd sha256 $f
;   2. Build with the SIGN symbol defined and the sign tool registered:
;         iscc /DSIGN /Smysigntool="..." installer\AstromechOSImager.iss
;
; The PyInstaller-produced .exe inside dist\AstromechOS Imager\ should
; also be signed separately (signtool.exe sign … "AstromechOS Imager.exe")
; before iscc is invoked, so the inner bundle is signed too.
#ifdef SIGN
  SignTool=mysigntool $f
  SignedUninstaller=yes
#endif

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
