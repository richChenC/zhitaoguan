﻿; 在役检查系统-指套管数据管理工具 安装包脚本（Inno Setup 6）
;
; 构建前准备：
;   1. powershell -File scripts\build-backend.ps1   （后端 exe）
;   2. powershell -File scripts\build-shell.ps1     （Qt 壳 exe）
; 编译：
;   ISCC.exe scripts\thimble-installer.iss
; 产物输出到 07_软件发布包\installer\。

#define MyAppName "在役检查系统-指套管数据管理工具"
#define MyAppVersion "2026.11.06.9"
#define MyAppPublisher "ThimbleInspection"
#define MyAppExeName "在役检查系统-指套管数据管理工具.exe"
; 本脚本位于 scripts\ 下，相对路径以脚本所在目录为基准解析
#ifndef THIMBLE_SHELL_SOURCE
  #define THIMBLE_SHELL_SOURCE "..\build\shell\在役检查系统-指套管数据管理工具"
#endif
#ifndef THIMBLE_BACKEND_SOURCE
  #define THIMBLE_BACKEND_SOURCE "..\build\backend\thimble-backend.exe"
#endif
#ifndef THIMBLE_OUTPUT_DIR
  #define THIMBLE_OUTPUT_DIR "..\..\07_软件发布包\installer"
#endif

[Setup]
AppId={{A4D8B2F7-6C31-4E95-9F20-7B5E1D3C8A64}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableDirPage=no
DefaultGroupName={#MyAppName}
OutputDir={#THIMBLE_OUTPUT_DIR}
OutputBaseFilename={#MyAppName}-安装包-{#MyAppVersion}-x64
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayName={#MyAppName}
SetupIconFile=..\assets\app-icon.ico
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
; Qt 壳主程序与运行时（exe + _internal）
Source: "{#THIMBLE_SHELL_SOURCE}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 后端数据服务
Source: "{#THIMBLE_BACKEND_SOURCE}"; DestDir: "{app}\build\backend"; Flags: ignoreversion
; 业务资源（与 constants.QT_ROOT 冻结布局保持一致）
Source: "..\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\.vendor\*"; DestDir: "{app}\.vendor"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[UninstallDelete]
; This per-install setting is generated after file installation, so Inno does
; not track it as a [Files] entry. Delete only the setting, never user data.
Type: files; Name: "{app}\data-location.json"

[InstallDelete]
; 覆盖安装/升级前先清除旧版程序负载，避免旧版 DLL 残留与新版本混装
;（旧 icu/api-ms-win 残留曾导致 QtCore 加载失败、程序无法启动）。
; 只清程序目录：{app} 根部的 data-location.json 与用户数据目录不受影响。
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\docs"
Type: filesandordirs; Name: "{app}\assets"
Type: filesandordirs; Name: "{app}\.vendor"

[Code]
var
  DataDirPage: TInputDirWizardPage;

function JsonUnescape(const S: String): String;
var
  I, Code: Integer;
  Hex: String;
begin
  Result := '';
  I := 1;
  while I <= Length(S) do
  begin
    if (S[I] = '\') and (I < Length(S)) then
    begin
      if S[I + 1] = '\' then
      begin
        Result := Result + '\';
        I := I + 2;
      end
      else if S[I + 1] = '"' then
      begin
        Result := Result + '"';
        I := I + 2;
      end
      else if (S[I + 1] = 'u') and (I + 5 <= Length(S)) then
      begin
        Hex := Copy(S, I + 2, 4);
        Code := StrToIntDef('$' + Hex, -1);
        if Code >= 0 then
        begin
          Result := Result + Chr(Code);
          I := I + 6;
        end
        else
        begin
          Result := Result + S[I];
          I := I + 1;
        end;
      end
      else
      begin
        Result := Result + S[I];
        I := I + 1;
      end;
    end
    else
    begin
      Result := Result + S[I];
      I := I + 1;
    end;
  end;
end;

function ExistingDataDir(const AppDir: String): String;
var
  ConfigPath: String;
  Content: AnsiString;
  Text, Key: String;
  StartPos, EndPos: Integer;
begin
  Result := '';
  ConfigPath := AppDir + '\data-location.json';
  if not FileExists(ConfigPath) then
    exit;
  if not LoadStringFromFile(ConfigPath, Content) then
    exit;
  Text := String(Content);
  Key := '"user_data_dir":"';
  StartPos := Pos(Key, Text);
  if StartPos = 0 then
    exit;
  StartPos := StartPos + Length(Key);
  EndPos := Pos('"}', Copy(Text, StartPos, MaxInt));
  if EndPos = 0 then
    exit;
  Result := JsonUnescape(Copy(Text, StartPos, EndPos - 1));
end;

procedure InitializeWizard();
begin
  DataDirPage := CreateInputDirPage(
    wpSelectDir,
    '选择数据存放目录', '业务数据保存在哪里？',
    '数据库、导出文件和运行日志将保存在下面的目录中。' +
    '重装或升级软件不会删除该目录；更换电脑时拷贝此目录即可迁移全部数据。',
    False, '');
  DataDirPage.Add('数据目录（可修改为非系统盘，如 D:\ThimbleData）：');
  DataDirPage.Values[0] := ExpandConstant('{localappdata}\ThimbleInspection\user-data');
end;

procedure SetDataDirFromPreviousInstall();
var
  Previous: String;
begin
  // {app} 在向导初始化阶段尚未可用，只能在离开安装目录页之后再读取旧配置。
  Previous := ExistingDataDir(WizardDirValue);
  if Previous <> '' then
    DataDirPage.Values[0] := Previous;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
    SetDataDirFromPreviousInstall();
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // 静默安装不会触发 NextButtonClick，在这里兜底沿用旧数据目录。
  SetDataDirFromPreviousInstall();
  Result := '';
end;

function JsonEscape(const S: String): String;
var
  I: Integer;
  C: Char;
begin
  Result := '';
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if C = '\' then
      Result := Result + '\\'
    else if C = '"' then
      Result := Result + '\"'
    else if (Ord(C) < 32) or (Ord(C) > 126) then
      // 非 ASCII 一律转义为 \uXXXX，保证配置文件为纯 ASCII，
      // 避免 Inno 按 ANSI 写文件时中文路径被错误编码。
      Result := Result + Format('\u%.4x', [Ord(C)])
    else
      Result := Result + C;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigPath: String;
  Content: AnsiString;
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(DataDirPage.Values[0]);
    ConfigPath := ExpandConstant('{app}\data-location.json');
    Content := '{"user_data_dir":"' + AnsiString(JsonEscape(DataDirPage.Values[0])) + '"}';
    SaveStringToFile(ConfigPath, Content, False);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // 业务数据目录不在安装目录内，卸载天然不会触碰；
  // 仅在交互模式下告知用户数据去向，静默模式（/VERYSILENT）不得弹窗，
  // 否则无人值守卸载会因等待确认而挂起。
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent()) then
    MsgBox('卸载完成。业务数据目录（数据库、导出、日志）已保留，' +
           '需要时可手动清理。', mbInformation, MB_OK);
end;
