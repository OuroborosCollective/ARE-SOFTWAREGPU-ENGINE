#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef Version
  #error Version is required
#endif

[Setup]
AppId={{857C5924-3D21-4CA3-9806-1A5F0ADCA953}
AppName=ARE SoftwareGPU
AppVersion={#Version}
AppPublisher=Thomas Markgraf (OuroborosCollective)
AppPublisherURL=https://arelogic.space/projects/are-softwaregpu-engine/
AppSupportURL=https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues
DefaultDirName={localappdata}\Programs\ARE-SoftwareGPU
DefaultGroupName=ARE SoftwareGPU
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#SourceDir}\LICENSE.md
OutputDir={#OutputDir}
OutputBaseFilename=ARE-SoftwareGPU-{#Version}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\are-softwaregpu.exe
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ARE SoftwareGPU Console"; Filename: "{app}\ARE SoftwareGPU Console.cmd"; WorkingDir: "{userdocs}"
Name: "{group}\Uninstall ARE SoftwareGPU"; Filename: "{uninstallexe}"
