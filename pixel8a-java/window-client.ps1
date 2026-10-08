param([Parameter(Mandatory = $true)][string]$Title)
$ErrorActionPreference = 'Stop'

$source = @'
using System;
using System.Runtime.InteropServices;
public static class Pixel8aWindow {
    [StructLayout(LayoutKind.Sequential)] public struct Rect {
        public int Left, Top, Right, Bottom;
    }
    [StructLayout(LayoutKind.Sequential)] public struct Point {
        public int X, Y;
    }
    [DllImport("user32.dll")]
    public static extern bool GetClientRect(IntPtr handle, out Rect rect);
    [DllImport("user32.dll")]
    public static extern bool ClientToScreen(IntPtr handle, ref Point point);
}
'@
Add-Type -TypeDefinition $source
$matches = @(Get-Process -Name scrcpy -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -eq $Title -and $_.MainWindowHandle -ne [IntPtr]::Zero })
if ($matches.Count -ne 1) {
    [Console]::Error.WriteLine("scrcpy window '$Title' was not found. Open the game mirror, then retry preview.")
    exit 2
}
$handle = $matches[0].MainWindowHandle
$rect = New-Object Pixel8aWindow+Rect
$point = New-Object Pixel8aWindow+Point
if (-not [Pixel8aWindow]::GetClientRect($handle, [ref]$rect) -or
    -not [Pixel8aWindow]::ClientToScreen($handle, [ref]$point)) {
    [Console]::Error.WriteLine('Could not locate the scrcpy game image.')
    exit 3
}
if ($rect.Right - $rect.Left -lt 100 -or $rect.Bottom - $rect.Top -lt 200) {
    [Console]::Error.WriteLine('The scrcpy window is too small or minimized.')
    exit 4
}
$coordinates = @($point.X, $point.Y, ($rect.Right - $rect.Left),
    ($rect.Bottom - $rect.Top))
[Console]::Out.WriteLine([string]::Join(',', $coordinates))
