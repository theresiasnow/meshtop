; Inno Setup script for meshtop
; Build: iscc /DAppVersion=v0.4.1 meshtop.iss

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppName=meshtop
AppVersion={#AppVersion}
AppPublisher=theresiasnow
AppPublisherURL=https://github.com/theresiasnow/meshtop
AppSupportURL=https://github.com/theresiasnow/meshtop/issues
DefaultDirName={autopf}\meshtop
DefaultGroupName=meshtop
OutputDir=installer
OutputBaseFilename=meshtop-{#AppVersion}-setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\meshtop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\meshtop"; Filename: "{app}\meshtop.exe"; \
  Comment: "Meshtastic GPS bridge"
Name: "{group}\Uninstall meshtop"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\meshtop.exe"; Parameters: "--help"; \
  Description: "Verify installation"; Flags: nowait postinstall skipifsilent
