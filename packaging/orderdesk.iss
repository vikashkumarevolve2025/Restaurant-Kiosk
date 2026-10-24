; Inno Setup recipe: wraps the PyInstaller folder in a normal Windows installer.
; Build:  ISCC.exe /DAppVersion=0.2.0 packaging\orderdesk.iss     (output goes to packaging\Output)
#define AppName "OrderDesk"
#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#define AppExe "OrderDesk.exe"
#define Port "8000"

[Setup]
; Keep this id the same in every release so upgrades replace the old install.
AppId={{7C0A3D5E-2B1F-4E86-9A54-5E1C6B8D2F40}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Your Name
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=OrderDesk-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}

[Tasks]
Name: "autostart"; Description: "Start {#AppName} automatically when Windows starts (recommended)"
Name: "desktopicon"; Description: "Put a {#AppName} icon on the desktop"

[Dirs]
; Orders, settings, backups and logs live here, so upgrades and uninstalls never touch them.
Name: "{commonappdata}\{#AppName}"; Permissions: users-modify

[Files]
Source: "..\dist\OrderDesk\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Start {#AppName}"; Filename: "{app}\{#AppExe}"; Flags: runminimized
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Flags: runminimized; Tasks: desktopicon
Name: "{commonstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--no-browser"; Flags: runminimized; Tasks: autostart
Name: "{group}\Counter screen, full screen"; Filename: "{commonpf32}\Microsoft\Edge\Application\msedge.exe"; Parameters: "--kiosk http://127.0.0.1:{#Port}/ --edge-kiosk-type=fullscreen"; Check: EdgeInstalled
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[INI]
Filename: "{group}\Counter screen.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://127.0.0.1:{#Port}/"
Filename: "{group}\Kitchen screen.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://127.0.0.1:{#Port}/kitchen"
Filename: "{group}\Admin.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://127.0.0.1:{#Port}/admin"
Filename: "{group}\Table QR codes.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://127.0.0.1:{#Port}/tables"

[Run]
; Let phones on the shop network reach the program. Only addresses inside the local network are allowed.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=any remoteip=localsubnet"; Flags: runhidden
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now and set it up"; Flags: nowait postinstall skipifsilent runminimized

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; RunOnceId: "RemoveFirewallRule"

[Code]
function EdgeInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf32}\Microsoft\Edge\Application\msedge.exe'));
end;

// Stop a running copy so an upgrade can replace its files.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
