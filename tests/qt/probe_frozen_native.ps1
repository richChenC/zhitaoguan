param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$Database,
    [Parameter(Mandatory)][string]$Output,
    [string]$RptDirectory
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
    public static bool ClickWindow(IntPtr handle, int x, int y) {
        var p=new Point { X=x, Y=y };
        if(!ScreenToClient(handle,ref p)) return false;
        var position=new IntPtr((p.Y<<16)|(p.X&0xFFFF));
        PostMessage(handle,0x0201,new IntPtr(1),position);
        PostMessage(handle,0x0202,IntPtr.Zero,position);
        return true;
    }
    public static bool RightClickWindow(IntPtr handle, int x, int y) {
        var p=new Point { X=x, Y=y };
        if(!ScreenToClient(handle,ref p)) return false;
        var position=new IntPtr((p.Y<<16)|(p.X&0xFFFF));
        PostMessage(handle,0x0204,new IntPtr(2),position);
        PostMessage(handle,0x0205,IntPtr.Zero,position);
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
if ($RptDirectory) {
    $RptDirectory = (Resolve-Path -LiteralPath $RptDirectory -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $RptDirectory -PathType Container)) {
        throw 'RPT reference path must be an existing directory'
    }
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
        if ($label -eq '数据可视化') {
            $historyTabs = Find-Control $window ([System.Windows.Automation.ControlType]::TabItem) '单管完整历史'
            if ($historyTabs.Count -ne 1) { throw 'Complete tube history tab missing' }
            $historyTabs[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
            $historyExport = @()
            for ($attempt=0; $attempt -lt 100; $attempt++) {
                Start-Sleep -Milliseconds 150
                $historyExport = @(Find-Control $window ([System.Windows.Automation.ControlType]::Button) '导出 CSV' |
                    Where-Object { -not $_.Current.IsOffscreen -and $_.Current.IsEnabled })
                if ($historyExport.Count -eq 1) { break }
            }
            if ($historyExport.Count -ne 1) { throw 'Complete tube history did not finish loading' }
            $result.history_scope_controls = @('完整历史基地', '完整历史机组' | ForEach-Object {
                $controls = Find-Control $window ([System.Windows.Automation.ControlType]::ComboBox) $_
                if ($controls.Count -ne 1 -or $controls[0].Current.IsOffscreen) {
                    throw "Complete history scope selector missing: $_"
                }
                $_
            })
            Capture 'frozen-complete-history'
            $expandHistory = Find-Control $window ([System.Windows.Automation.ControlType]::Button) '全部展开'
            if ($expandHistory.Count -ne 1) { throw 'History expand action missing' }
            Activate-Control $expandHistory[0]
            Start-Sleep -Milliseconds 300
            $originalJumps = Find-Control $window ([System.Windows.Automation.ControlType]::Button) '在工作台查看原始记录'
            if ($originalJumps.Count -eq 0) { throw 'Expanded original history records missing' }
            $result.history_original_rounds = $originalJumps.Count
            $collapseHistory = Find-Control $window ([System.Windows.Automation.ControlType]::Button) '全部折叠'
            Activate-Control $collapseHistory[0]
            $result.steps += 'native-complete-history-load-expand-collapse'
            foreach ($tabName in @('磨损趋势', '群厂趋势')) {
                $chartTabs = @(Find-Control $window ([System.Windows.Automation.ControlType]::TabItem) $tabName |
                    Where-Object { -not $_.Current.IsOffscreen })
                if ($chartTabs.Count -ne 1) { throw "Native chart tab missing: $tabName" }
                $chartTabs[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
                Start-Sleep -Milliseconds 250
            }
            $popout = @(Find-Control $window ([System.Windows.Automation.ControlType]::Button) '在独立窗口中对比' |
                Where-Object { -not $_.Current.IsOffscreen -and $_.Current.IsEnabled })
            if ($popout.Count -ne 1) { throw "Expected one visible native chart comparison action: $($popout.Count)" }
            Activate-Control $popout[0]
            $chartHandle = [IntPtr]::Zero
            for ($attempt=0; $attempt -lt 100 -and $chartHandle -eq [IntPtr]::Zero; $attempt++) {
                Start-Sleep -Milliseconds 100
                $chartHandle = [NativeProbeWindow]::FindNamed($process.Id, '群厂 WAR 报告深度趋势')
            }
            if ($chartHandle -eq [IntPtr]::Zero) { throw 'Independent native chart did not appear' }
            $mainWindow = $window
            $window = [System.Windows.Automation.AutomationElement]::FromHandle($chartHandle)
            Start-Sleep -Milliseconds 1200
            if ((Find-Control $window ([System.Windows.Automation.ControlType]::Button) '放大查看').Count -ne 1) {
                throw 'Independent native chart controls missing'
            }
            Capture 'frozen-independent-chart'
            [NativeProbeWindow]::PostMessage($chartHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
            Start-Sleep -Milliseconds 250
            $window = $mainWindow
            $result.steps += 'native-independent-chart-open-close'
        }
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
            $activePlateButton = Find-NamedControl $window '管板图：开'
            Activate-Control $activePlateButton[0]
            $result.three_d_camera_views = @()
            foreach ($cameraName in @('正视','后视','左视','右视','俯视','仰视','等轴视角')) {
                $cameraControl = @(Find-NamedControl $window $cameraName |
                    Where-Object { -not $_.Current.IsOffscreen -and $_.Current.IsEnabled })
                if ($cameraControl.Count -ne 1) { throw "Native camera control missing: $cameraName" }
                Activate-Control $cameraControl[0]
                Start-Sleep -Milliseconds 300
                Capture ('frozen-three-d-camera-' + $result.three_d_camera_views.Count)
                $result.three_d_camera_views += $cameraName
            }
            $topCameraControl = @(Find-NamedControl $window '俯视' |
                Where-Object { -not $_.Current.IsOffscreen -and $_.Current.IsEnabled })
            Activate-Control $topCameraControl[0]
            $inactivePlateButton = Find-NamedControl $window '管板图：关'
            Activate-Control $inactivePlateButton[0]
            Start-Sleep -Milliseconds 350
            Capture 'frozen-three-d-top-readable-overlay'
            $result.steps += 'native-top-mirrored-plate-overlay'
            $result.steps += 'native-seven-camera-view-controls'
            $result.steps += 'native-plate-overlay-controls'
            $result.steps += 'real-data-3D-scope-controls'
            $topOverlayOff = Find-NamedControl $window '管板图：开'
            Activate-Control $topOverlayOff[0]
            $isoCamera = @(Find-NamedControl $window '等轴视角' |
                Where-Object { -not $_.Current.IsOffscreen -and $_.Current.IsEnabled })
            Activate-Control $isoCamera[0]
            $modelSettings = Find-NamedControl $window '三维显示设置'
            if ($modelSettings.Count -ne 1) { throw 'Native floating model settings action missing' }
            Activate-Control $modelSettings[0]
            Start-Sleep -Milliseconds 300
            $modelPanel = Find-NamedControl $window '三维模型设置'
            if ($modelPanel.Count -ne 1 -or $modelPanel[0].Current.IsOffscreen) {
                throw 'Native floating model settings panel did not open'
            }
            $result.three_d_color_controls = @()
            foreach ($colorName in @('按管长着色', '按型号着色', '按检测数据着色（最大磨损）')) {
                $colorControl = Find-NamedControl $window $colorName
                if ($colorControl.Count -ne 1) { throw "Native model color action missing: $colorName" }
                Activate-Control $colorControl[0]
                Start-Sleep -Milliseconds 200
                $toggle = $colorControl[0].GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
                if ($toggle.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::On) {
                    throw "Native model color action did not toggle: $colorName"
                }
                $result.three_d_color_controls += $colorName
            }
            Capture 'frozen-three-d-floating-settings-depth'
            $typeLegend = Find-NamedControl $window '筛选Ⅱ型'
            if ($typeLegend.Count -ne 1) { throw 'Native model type legend action missing' }
            Activate-Control $typeLegend[0]
            Start-Sleep -Milliseconds 200
            Capture 'frozen-three-d-floating-settings-filter'
            Activate-Control $typeLegend[0]
            $result.three_d_parts = @()
            foreach ($partName in @('指套管本体', '螺纹管座', '配合螺栓（管段样件）',
                                      '调整螺母', '中子测量贯穿管', '空心二次支承柱')) {
                $partItems = @(Find-Control $window ([System.Windows.Automation.ControlType]::TreeItem) |
                    Where-Object { $_.Current.Name.StartsWith($partName + '，') })
                if ($partItems.Count -ne 1) { throw "Native part tree item missing: $partName" }
                $bounds = $partItems[0].Current.BoundingRectangle
                if (-not [NativeProbeWindow]::ClickWindow([IntPtr]$window.Current.NativeWindowHandle,
                    [int]($bounds.X+40), [int]($bounds.Y+$bounds.Height/2))) { throw 'Part tree click failed' }
                Start-Sleep -Milliseconds 250
                $partClose = Find-NamedControl $window '关闭零件详情'
                $partDetails = Find-NamedControl $window '三维零件详情'
                if ($partClose.Count -ne 1 -or $partClose[0].Current.IsOffscreen -or
                    $partDetails.Count -ne 1 -or $partDetails[0].Current.IsOffscreen) {
                    throw "Native part metadata did not open: $partName"
                }
                $partLabels = @(Find-Control $window ([System.Windows.Automation.ControlType]::Text) |
                    ForEach-Object { $_.Current.Name })
                if (-not ($partLabels | Where-Object { $_ -like '*三角面*' })) {
                    throw "Native part triangle/source metadata missing: $partName"
                }
                Capture ('frozen-three-d-part-' + $result.three_d_parts.Count)
                if (-not [NativeProbeWindow]::RightClickWindow([IntPtr]$window.Current.NativeWindowHandle,
                    [int]($bounds.X+40), [int]($bounds.Y+$bounds.Height/2))) { throw 'Part context click failed' }
                Start-Sleep -Milliseconds 150
                $hiddenItems = @(Find-Control $window ([System.Windows.Automation.ControlType]::TreeItem) |
                    Where-Object { $_.Current.Name.StartsWith($partName + '，隐藏') })
                if ($hiddenItems.Count -ne 1) { throw "Part context click did not hide: $partName" }
                [NativeProbeWindow]::ClickWindow([IntPtr]$window.Current.NativeWindowHandle,
                    [int]($bounds.X+40), [int]($bounds.Y+$bounds.Height/2)) | Out-Null
                Start-Sleep -Milliseconds 150
                $restoredItems = @(Find-Control $window ([System.Windows.Automation.ControlType]::TreeItem) |
                    Where-Object { $_.Current.Name.StartsWith($partName + '，显示') })
                if ($restoredItems.Count -ne 1) { throw "Part click did not restore: $partName" }
                $result.three_d_parts += $partName
            }
            foreach ($annotationName in @('尺寸标注','P1–P6 轴向标记')) {
                $annotationControl = Find-NamedControl $window $annotationName
                if ($annotationControl.Count -ne 1 -or -not $annotationControl[0].Current.IsEnabled) {
                    throw "Native annotation control missing or disabled in detail: $annotationName"
                }
                Activate-Control $annotationControl[0]
                Start-Sleep -Milliseconds 100
                Activate-Control $annotationControl[0]
            }
            $partClose = Find-NamedControl $window '关闭零件详情'
            Activate-Control $partClose[0]
            $fullTab = Find-Control $window ([System.Windows.Automation.ControlType]::TabItem) '整管视图'
            $fullTab[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
            Activate-Control $modelSettings[0]
            Activate-Control $filterButton[0]
            Start-Sleep -Milliseconds 350
            $axisScale = @(Find-NamedControl $window 'P1–P6 轴向标尺' |
                Where-Object { -not $_.Current.IsOffscreen })
            if ($axisScale.Count -ne 1) { throw 'Native full-length axial scale did not become accessible' }
            $p5Ticks = @(Find-Control $window ([System.Windows.Automation.ControlType]::Button) |
                Where-Object { $_.Current.Name.StartsWith('P5? · ') -and -not $_.Current.IsOffscreen })
            if ($p5Ticks.Count -ne 1) { throw 'Native estimated P5 scale tick missing' }
            Activate-Control $p5Ticks[0]
            Start-Sleep -Milliseconds 150
            Capture 'frozen-three-d-axial-scale'
            Activate-Control $modelSettings[0]
            Start-Sleep -Milliseconds 150
            $axisScale = @(Find-NamedControl $window 'P1–P6 轴向标尺' |
                Where-Object { -not $_.Current.IsOffscreen })
            if ($axisScale.Count -ne 0) { throw 'Native model controls failed to hide the axial scale' }
            $assemblyTab = Find-Control $window ([System.Windows.Automation.ControlType]::TabItem) '整体布置'
            if ($assemblyTab.Count -ne 1) { throw 'Assembly mode tab missing after part details' }
            $assemblyTab[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
            Start-Sleep -Milliseconds 150
            Activate-Control $modelSettings[0]
            $result.steps += 'native-floating-model-settings-colors-and-type-filter'
            $result.steps += 'native-six-part-tree-metadata-right-click-hide-and-restore'
            $result.steps += 'native-dimensions-station-rings-and-accessible-axial-scale'
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
    if ($RptDirectory) {
        $sourcePath = Find-Control $window ([System.Windows.Automation.ControlType]::Edit) '导入来源路径'
        if ($sourcePath.Count -ne 1) { throw 'Native import source path missing' }
        $sourcePath[0].GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($RptDirectory)
        $scan = Find-Control $window ([System.Windows.Automation.ControlType]::Button) '检查数据'
        if ($scan.Count -ne 1) { throw 'Native RPT scan action missing' }
        Activate-Control $scan[0]
        $choiceHandle = [IntPtr]::Zero
        for ($attempt=0; $attempt -lt 600 -and $choiceHandle -eq [IntPtr]::Zero; $attempt++) {
            Start-Sleep -Milliseconds 150
            $choiceHandle = [NativeProbeWindow]::FindNamed($process.Id, '选择分析报告')
        }
        if ($choiceHandle -eq [IntPtr]::Zero) { throw 'RPT companion window did not open after real scan' }
        $window = [System.Windows.Automation.AutomationElement]::FromHandle($choiceHandle)
        Capture 'frozen-rpt-companion'
        $confirmedGroups = 0
        $result.rpt_group_selection = @()
        while ($confirmedGroups -lt 200) {
            $radios = Find-Control $window ([System.Windows.Automation.ControlType]::RadioButton)
            if ($radios.Count -eq 0) { throw 'RPT report candidates missing' }
            $candidateName = $radios[0].Current.Name
            $candidateBounds = $radios[0].Current.BoundingRectangle
            if (-not [NativeProbeWindow]::ClickWindow($choiceHandle,
                [int]($candidateBounds.X+$candidateBounds.Width/2),
                [int]($candidateBounds.Y+$candidateBounds.Height/2))) { throw 'Could not click RPT candidate' }
            $selection = $radios[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
            for ($attempt=0; $attempt -lt 40 -and -not $selection.Current.IsSelected; $attempt++) {
                Start-Sleep -Milliseconds 50
            }
            if (-not $selection.Current.IsSelected) { Capture 'frozen-rpt-unselected'; throw 'RPT candidate did not become selected' }
            $result.rpt_group_selection += $candidateName
            $finishChoice = Find-Control $window ([System.Windows.Automation.ControlType]::Button) '完成确认'
            if ($finishChoice.Count -eq 1) {
                Activate-Control $finishChoice[0]
                $confirmedGroups++
                break
            }
            $nextChoice = Find-Control $window ([System.Windows.Automation.ControlType]::Button) '下一个'
            if ($nextChoice.Count -ne 1) { throw 'RPT next-group action missing' }
            Activate-Control $nextChoice[0]
            $confirmedGroups++
            $nextGroupNumber = $confirmedGroups + 1
            $advanced = $false
            for ($attempt=0; $attempt -lt 40 -and -not $advanced; $attempt++) {
                Start-Sleep -Milliseconds 50
                $stepLabels = Find-Control $window ([System.Windows.Automation.ControlType]::Text)
                $advanced = @($stepLabels | Where-Object {
                    $_.Current.Name -like "Report 确认 $nextGroupNumber / *"
                }).Count -gt 0
            }
            if (-not $advanced) { Capture 'frozen-rpt-no-advance'; throw 'RPT group confirmation did not advance' }
        }
        for ($attempt=0; $attempt -lt 40; $attempt++) {
            if ([NativeProbeWindow]::FindNamed($process.Id, '选择分析报告') -eq [IntPtr]::Zero) { break }
            Start-Sleep -Milliseconds 50
        }
        if ([NativeProbeWindow]::FindNamed($process.Id, '选择分析报告') -ne [IntPtr]::Zero) {
            Capture 'frozen-rpt-incomplete'
            throw 'Explicit RPT confirmation did not close the companion window'
        }
        $window = $importWindow
        $summaryLabels = Find-Control $window ([System.Windows.Automation.ControlType]::Text)
        if (-not @($summaryLabels | Where-Object { $_.Current.Name -like '*可生成标准 Excel 或预检入库*' }).Count) {
            throw 'RPT confirmation summary did not become ready'
        }
        $result.rpt_confirmed_groups = $confirmedGroups
        $result.steps += 'native-real-rpt-companion-explicit-confirmation'
        Capture 'frozen-rpt-confirmed-summary'
    }
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
        $choiceHandle = [NativeProbeWindow]::FindNamed($process.Id, '选择分析报告')
        if ($choiceHandle -ne [IntPtr]::Zero) {
            [NativeProbeWindow]::PostMessage($choiceHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
            Start-Sleep -Milliseconds 200
        }
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
