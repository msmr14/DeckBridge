$target = Join-Path $env:LOCALAPPDATA "Programs\DeckBridge"
# Stop running instance if any to release file locks
Get-Process -Name "DeckBridge*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 300

if (Test-Path $target) {
    Remove-Item $target -Recurse -Force
}
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -Path "dist\DeckBridge\*" -Destination $target -Recurse -Force
if (Test-Path "DeckBridge.ico") {
    Copy-Item -Path "DeckBridge.ico" -Destination $target -Force
}
Write-Host "Deployed DeckBridge to: $target"

# Create Desktop Shortcut
$wsh = New-Object -ComObject WScript.Shell
$desktop = [System.Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop "DeckBridge.lnk"
$shortcut = $wsh.CreateShortcut($shortcutPath)
$exePath = Join-Path $target "DeckBridge.exe"
$shortcut.TargetPath = $exePath
$shortcut.WorkingDirectory = $target
$shortcut.IconLocation = "$exePath, 0"
$shortcut.Description = "DeckBridge: Non-Steam Game & Artwork Tool for Steam"
$shortcut.Save()

Write-Host "Desktop shortcut created at: $shortcutPath"

# Refresh Windows Shell icon cache so desktop reflects the icon immediately
try {
    Add-Type -TypeDefinition @"
    using System;
    using System.Runtime.InteropServices;
    public class WinShellNotify {
        [DllImport("shell32.dll")]
        public static extern void SHChangeNotify(int wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);
    }
"@ -ErrorAction SilentlyContinue
    [WinShellNotify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
    Write-Host "Notified Windows Shell of icon update (SHCNE_ASSOCCHANGED)."
} catch {
    Write-Warning "Shell notification fallback: $_"
}

try {
    Start-Process -FilePath "ie4uinit.exe" -ArgumentList "-show" -WindowStyle Hidden -ErrorAction SilentlyContinue
} catch {}
