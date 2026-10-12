; Browser Agent — Windows installer (Inno Setup 6).
; Build it with:  build_installer.bat
;   1. runs PyInstaller (BrowserAgent.spec) -> dist\BrowserAgent\
;   2. compiles this script -> dist-installer\BrowserAgent-Setup-<version>.exe
; Install Inno Setup once from https://jrsoftware.org/isinfo.php (free).
;
; Per-user install: no admin rights needed. Installs to
; %LOCALAPPDATA%\Programs\BrowserAgent, Start Menu shortcut, optional desktop
; icon, and an entry in "Add or remove programs" (automatic uninstaller).
; Settings (.env), history DB, logs and screenshots live next to the install
; and are created on first run — they are never overwritten by reinstalls.

#define MyAppName "Browser Agent"
#define MyAppVersion "0.3.1"
#define MyAppPublisher "BrowserAgent"
#define MyAppExeName "BrowserAgent.exe"

[Setup]
AppId={{3E8B4C1A-7F2D-4E6A-9B5C-1D2F3A4B5C6D7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\BrowserAgent
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=dist-installer
OutputBaseFilename=BrowserAgent-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole PyInstaller onedir folder — exe plus its runtime files.
; The user's own .env is created by the app on first run and lives outside
; this list's control, so reinstalls never overwrite it.
Source: "dist\BrowserAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
