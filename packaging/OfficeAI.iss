#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#ifndef AppSourceDir
  #define AppSourceDir GetEnv("OFFICEAI_PACKAGE_DIR")
#endif

[Setup]
AppId={{E22BF0B1-9A86-48F2-94C6-CE05FAED0A10}
AppName=Office AI
AppVersion={#AppVersion}
AppPublisher=Office AI
DefaultDirName={localappdata}\Programs\Office AI
DefaultGroupName=Office AI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=OfficeAI-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\OfficeAI.exe

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Office AI"; Filename: "{app}\OfficeAI.exe"
Name: "{autodesktop}\Office AI"; Filename: "{app}\OfficeAI.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные значки:"; Flags: unchecked
