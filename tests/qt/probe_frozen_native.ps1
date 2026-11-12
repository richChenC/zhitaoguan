param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$Database,
    [Parameter(Mandatory)][string]$Output
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class NativeProbeWindow {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct Point { public int X, Y; }
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int command);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    public delegate bool Callback(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(Callback cb, IntPtr l);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder b, int n);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out Rect r);
    [DllImport("user32.dll")] static extern bool ScreenToClient(IntPtr h, ref Point p);
    public static bool ClickInPopup(uint pid, int x, int y) {
        IntPtr popup=IntPtr.Zero, main=Find(pid);
        int area=int.MaxValue;
        EnumWindows((h,l)=> {
            uint owner; GetWindowThreadProcessId(h,out owner);
            Rect r;
            if(owner==pid && h!=main && IsWindowVisible(h) && GetWindowRect(h,out r) &&
               x>=r.Left && x<r.Right && y>=r.Top && y<r.Bottom) {
                int candidate=(r.Right-r.Left)*(r.Bottom-r.Top);
                if(candidate<area) { popup=h; area=candidate; }
            }
            return true;
        },IntPtr.Zero);
        if(popup==IntPtr.Zero) return false;
        var p=new Point { X=x, Y=y };
        if(!ScreenToClient(popup,ref p)) return false;
        var position=new IntPtr((p.Y<<16)|(p.X&0xFFFF));
        PostMessage(popup,0x0201,new IntPtr(1),position);
        PostMessage(popup,0x0202,IntPtr.Zero,position);
        return true;
    }
    public static IntPtr Find(uint pid) {
        IntPtr result=IntPtr.Zero, hidden=IntPtr.Zero;
        EnumWindows((h,l)=> {
            uint p; GetWindowThreadProcessId(h,out p);
            if(p==pid) {
                var b=new StringBuilder(512); GetWindowText(h,b,512);
                Rect r;
                if(b.ToString().Contains("指套管") &&
                   GetWindowRect(h,out r) && r.Right-r.Left>=500 && r.Bottom-r.Top>=300) {
                    if(IsWindowVisible(h)) { result=h; return false; }
                    hidden=h;
                }
            }
            return true;
        },IntPtr.Zero);
        return result!=IntPtr.Zero ? result : hidden;
    }
    public static IntPtr FindNamed(uint pid, string title) {
        IntPtr result=IntPtr.Zero;
        EnumWindows((h,l)=> {
            uint p; GetWindowThreadProcessId(h,out p);
            if(p==pid && IsWindowVisible(h)) {
                var b=new StringBuilder(512); GetWindowText(h,b,512);
                if(b.ToString()==title) { result=h; return false; }
            }
            return true;
        },IntPtr.Zero);
        return result;
    }
    public static Rect Bounds(IntPtr handle) {
        Rect bounds;
        if(!GetWindowRect(handle,out bounds)) throw new InvalidOperationException("GetWindowRect failed");
        return bounds;
    }
}
'@
$appRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$artifactRoot = [IO.Path]::GetFullPath((Join-Path $appRoot '../05_测试与验证/03_自动化临时产物')).TrimEnd('\') + '\'
$work = [IO.Path]::GetFullPath($Output)
if (-not $work.StartsWith($artifactRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Test output must remain inside $artifactRoot"
}
New-Item -ItemType Directory -Path (Join-Path $work 'data') -Force | Out-Null
$python = Join-Path $appRoot '.venv-qt/Scripts/python.exe'
& $python -c "import sqlite3,sys; from pathlib import Path; s=sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True); c=sqlite3.connect(sys.argv[2]); s.backup(c); s.close(); c.executescript('DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;'); c.commit(); c.close()" $Database (Join-Path $work 'data/thimble.db')
if ($LASTEXITCODE -ne 0) { throw 'Unable to isolate identities' }
$env:THIMBLE_QT_TEST_DATA_ROOT = $work
$env:THIMBLE_ALLOW_MULTI_INSTANCE = '1'
$env:THIMBLE_PORT = '18788'
$result = [ordered]@{ passed=$false; steps=@(); screenshots=@(); error=$null }
$process = $null
function Find-Window {
    $handle = [NativeProbeWindow]::Find($process.Id)
    if ($handle -ne [IntPtr]::Zero) {
        [NativeProbeWindow]::ShowWindow($handle, 9) | Out-Null
        return [System.Windows.Automation.AutomationElement]::FromHandle($handle)
    }
    return $null
}
function Wait-Window {
    for ($attempt=0; $attempt -lt 300; $attempt++) {
        if ($process.HasExited) { throw "Frozen application exited early: $($process.ExitCode)" }
        $window = Find-Window
        if ($window) { return $window }
        Start-Sleep -Milliseconds 200
    }
    $result.startup_processes = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -eq $process.Id -or $_.ParentProcessId -eq $process.Id
    } | Select-Object ProcessId, ParentProcessId, ExecutablePath)
    throw 'Native window did not appear within 60 seconds'
}
function Find-Control($window, $type, [string]$name='') {
    $conditions = [Collections.Generic.List[System.Windows.Automation.Condition]]::new()
    $conditions.Add([System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $type))
    if ($name) {
        $conditions.Add([System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::NameProperty, $name))
    }
    $condition = if ($conditions.Count -eq 1) { $conditions[0] } else {
        [System.Windows.Automation.AndCondition]::new($conditions.ToArray())
    }
    return $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
}
function Activate-Control($control) {
    $pattern = $null
    if ($control.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
        $pattern.Invoke()
    } elseif ($control.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) {
        $pattern.Toggle()
    } else {
        throw "Control cannot be activated: $($control.Current.Name)"
    }
}
function Find-NamedControl($window, [string]$name) {
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::NameProperty, $name)
    return $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
}
function Capture([string]$name) {
    $path = Join-Path $work ($name + '.png')
    # Capture only this process's window even when another app covers it.
    $bounds = [NativeProbeWindow]::Bounds([IntPtr]$window.Current.NativeWindowHandle)
    $bitmap = [Drawing.Bitmap]::new($bounds.Right-$bounds.Left, $bounds.Bottom-$bounds.Top)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    try {
        if (-not [NativeProbeWindow]::PrintWindow([IntPtr]$window.Current.NativeWindowHandle, $dc, 2)) {
            throw 'Target-window capture failed'
        }
    } finally {
        $graphics.ReleaseHdc($dc)
        $graphics.Dispose()
    }
    try { $bitmap.Save($path, [Drawing.Imaging.ImageFormat]::Png) }
    finally { $bitmap.Dispose() }
    $result.screenshots += $path
}
try {
    $process = Start-Process -FilePath $Exe -WindowStyle Hidden -PassThru
    $window = Wait-Window
    Start-Sleep -Milliseconds 1000
    [NativeProbeWindow]::ShowWindow([IntPtr]$window.Current.NativeWindowHandle, 5) | Out-Null
    [NativeProbeWindow]::ShowWindow([IntPtr]$window.Current.NativeWindowHandle, 9) | Out-Null
    Start-Sleep -Milliseconds 500
    $result.initial_window = @{handle=$window.Current.NativeWindowHandle; name=$window.Current.Name;
                              bounds=$window.Current.BoundingRectangle.ToString()}
    Capture 'frozen-login'
    $edits = Find-Control $window ([System.Windows.Automation.ControlType]::Edit)
    if ($edits.Count -ne 4) { throw "Expected four initialization fields; got $($edits.Count)" }
    $result.initialization_fields = @($edits | ForEach-Object { $_.Current.Name })
    $masked = @($edits | Where-Object { $_.Current.IsPassword })
    if ($masked.Count -ne 2) { throw 'Expected two masked password fields' }
    foreach ($edit in $edits) {
        $value = if ($edit.Current.IsPassword) { 'FrozenProbe@2026' } else {
            switch -Regex ($edit.Current.Name) {
                '^用户名$' { 'frozenprobe'; break }
                '^(姓名|显示名称)$' { 'Frozen Probe'; break }
                default { throw "Unrecognized initialization field: $($edit.Current.Name)" }
            }
        }
        $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($value)
    }
    # Reapply masked fields immediately before submit; no global keyboard input.
    foreach ($edit in $masked) {
        $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue('FrozenProbe@2026')
    }
    $submit = Find-Control $window ([System.Windows.Automation.ControlType]::Button) '创建管理员并进入'
    if ($submit.Count -ne 1) { throw 'Initialization button missing' }
    Activate-Control $submit[0]
    for ($attempt=0; $attempt -lt 100; $attempt++) {
        Start-Sleep -Milliseconds 200
        $window = Wait-Window
        if ($window.Current.Name -notlike '*本地登录*') { break }
    }
    if ($window.Current.Name -like '*本地登录*') { Capture 'frozen-initialization-failure'; throw 'Initialization did not enter main window' }
    Start-Sleep -Seconds 2
    $result.steps += 'actual-initialization-controls'
    Capture 'frozen-workbench'
    $tabs = Find-Control $window ([System.Windows.Automation.ControlType]::TabItem)
    $result.tabs = @($tabs | ForEach-Object { $_.Current.Name })
    foreach ($label in @('三维缺陷模型','数据可视化','报告中心','状态处理','数据工作台')) {
        $currentTabs = Find-Control $window ([System.Windows.Automation.ControlType]::TabItem) $label
        if ($currentTabs.Count -eq 0) { throw "Missing native navigation: $label" }
        $currentTabs[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
        Start-Sleep -Milliseconds 650
        $result.steps += $label
        if ($label -eq '三维缺陷模型') {
            Capture 'frozen-three-d-before-scope'
            $filterButton = Find-NamedControl $window '检测筛选'
            if ($filterButton.Count -ne 1) { throw 'Native 3D filter control missing' }
            Activate-Control $filterButton[0]
            Start-Sleep -Milliseconds 200
            $combos = @(Find-Control $window ([System.Windows.Automation.ControlType]::ComboBox) |
                Where-Object { -not $_.Current.IsOffscreen -and $_.Current.IsEnabled })
            if ($combos.Count -eq 0) { throw '3D scope selector missing' }
            $combo = $combos[0]
            $combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()
            Start-Sleep -Milliseconds 300
            $items = Find-Control $combo ([System.Windows.Automation.ControlType]::ListItem)
            $selected = @($items | Where-Object {
                $_.Current.Name -match '·' -and -not $_.Current.IsOffscreen
            } | Select-Object -First 1)
            if ($selected.Count -eq 0) { throw 'No visible real-data scope in the 3D dropdown' }
            $result.three_d_scope = $selected[0].Current.Name
            $itemBounds = $selected[0].Current.BoundingRectangle
            if (-not [NativeProbeWindow]::ClickInPopup($process.Id,
                [int]($itemBounds.X+$itemBounds.Width/2), [int]($itemBounds.Y+$itemBounds.Height/2))) {
                throw 'Could not click the target process dropdown'
            }
            Start-Sleep -Seconds 3
            $labels = Find-Control $window ([System.Windows.Automation.ControlType]::Text)
            $result.three_d_status = @($labels | Where-Object { $_.Current.Name -like '*已定位*' } |
                ForEach-Object { $_.Current.Name })
            Capture 'frozen-three-d-real-data'
            if ($result.three_d_status.Count -eq 0) { throw '3D real data did not finish loading' }
            $plateButton = Find-NamedControl $window '管板图：关'
            if ($plateButton.Count -ne 1) { throw 'Native 3D plate overlay control missing' }
            Activate-Control $plateButton[0]
            Start-Sleep -Milliseconds 450
            Capture 'frozen-three-d-plate-overlay'
            $result.steps += 'native-plate-overlay-controls'
            $result.steps += 'real-data-3D-scope-controls'
        }
    }
    $importButton = @(Find-Control $window ([System.Windows.Automation.ControlType]::Button) '导入数据' |
        Where-Object { -not $_.Current.IsOffscreen -and $_.Current.IsEnabled })
    if ($importButton.Count -ne 1) { throw 'Native import entry missing' }
    Activate-Control $importButton[0]
    $importWindow = $null
    for ($attempt=0; $attempt -lt 100 -and -not $importWindow; $attempt++) {
        Start-Sleep -Milliseconds 100
        $importHandle = [NativeProbeWindow]::FindNamed($process.Id, '导入检测数据')
        if ($importHandle -ne [IntPtr]::Zero) {
            $importWindow = [System.Windows.Automation.AutomationElement]::FromHandle($importHandle)
        }
    }
    if (-not $importWindow) { throw 'Native import workspace did not appear' }
    $window = $importWindow
    $sourceTabs = @(Find-Control $window ([System.Windows.Automation.ControlType]::TabItem))
    $result.import_tabs = @($sourceTabs | ForEach-Object { $_.Current.Name })
    $rptTab = @($sourceTabs | Where-Object { $_.Current.Name -like '*RPT 文件夹*' })
    if ($rptTab.Count -ne 1) { throw 'Persistent native import source tabs missing' }
    $rptTab[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
    Start-Sleep -Milliseconds 200
    if ((Find-Control $window ([System.Windows.Automation.ControlType]::Button) '选择检测文件夹').Count -ne 1) {
        throw 'Native RPT source route did not switch'
    }
    Capture 'frozen-native-import-rpt'
    [NativeProbeWindow]::PostMessage([IntPtr]$window.Current.NativeWindowHandle, 0x0010,
                                    [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 250
    $window = Wait-Window
    $result.steps += 'native-import-workspace-source-tabs'
    $result.loaded_modules = @($process.Modules | Where-Object { $_.ModuleName -match 'Qt6|WebEngine|Chromium' } |
        ForEach-Object { $_.ModuleName })
    if ($result.loaded_modules | Where-Object { $_ -match 'WebEngine|Chromium|WebChannel' }) {
        throw 'Browser modules were loaded'
    }
    Capture 'frozen-after-navigation'
    [NativeProbeWindow]::PostMessage([IntPtr]$window.Current.NativeWindowHandle, 0x0010,
                                    [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    if (-not $process.WaitForExit(20000)) { throw 'Normal WM_CLOSE did not terminate application' }
    $result.exit_code = $process.ExitCode
    if ($process.ExitCode -ne 0) { throw "Application exited with $($process.ExitCode)" }
    $result.passed = $true
} catch {
    $result.error = $_.ToString()
} finally {
    if ($process -and -not $process.HasExited) {
        $importHandle = [NativeProbeWindow]::FindNamed($process.Id, '导入检测数据')
        if ($importHandle -ne [IntPtr]::Zero) {
            [NativeProbeWindow]::PostMessage($importHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
            Start-Sleep -Milliseconds 200
        }
        $window = Find-Window
        if ($window) {
            [NativeProbeWindow]::PostMessage([IntPtr]$window.Current.NativeWindowHandle, 0x0010,
                                            [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
            $process.WaitForExit(10000) | Out-Null
        }
        if (-not $process.HasExited) {
            $process.Kill($true)
            $process.WaitForExit(5000) | Out-Null
            $result.cleanup_forced = $true
            $result.passed = $false
        }
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $work 'result.json') -Encoding utf8
    $result | ConvertTo-Json -Depth 8
}
if (-not $result.passed) { exit 1 }
