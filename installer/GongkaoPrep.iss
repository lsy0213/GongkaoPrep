; 上岸备考 安装包（Inno Setup 6）。build.bat 打包完成后自动调用：
;   ISCC /DAppVersion=0.3.0 installer\GongkaoPrep.iss
; 安装到当前用户目录（不需要管理员权限），学习数据在数据目录里，卸载不会删除。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0E5C2A-4D7F-4C55-9E1B-5A1F0C3D2B71}
AppName=上岸备考
AppVersion={#AppVersion}
AppPublisher=GongkaoPrep
AppPublisherURL=https://github.com/lsy0213/GongkaoPrep
DefaultDirName={localappdata}\Programs\GongkaoPrep
DefaultGroupName=上岸备考
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=GongkaoPrep-{#AppVersion}-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\GongkaoPrep.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "..\dist\GongkaoPrep\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\上岸备考"; Filename: "{app}\GongkaoPrep.exe"
Name: "{group}\卸载 上岸备考"; Filename: "{uninstallexe}"
Name: "{userdesktop}\上岸备考"; Filename: "{app}\GongkaoPrep.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GongkaoPrep.exe"; Description: "现在打开 上岸备考"; Flags: nowait postinstall skipifsilent
