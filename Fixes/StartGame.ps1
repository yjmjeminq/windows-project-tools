param([switch]$PrepareOnly)

$ErrorActionPreference = 'Stop'
$gameRoot = (Get-Item -LiteralPath (Split-Path -Parent $PSScriptRoot)).FullName

# The game's mod loader passes some paths through legacy narrow-string APIs.
# A local junction gives them an ASCII path to the same game and save files.
if ($gameRoot -match '[^\x20-\x7E]') {
    $aliasRoot = Join-Path $env:LOCALAPPDATA 'YGO-PC-Full\Installs'
    if ($aliasRoot -match '[^\x20-\x7E]') {
        $aliasRoot = Join-Path $env:PUBLIC 'Documents\YGO-PC-Full\Installs'
    }
    if ($aliasRoot -match '[^\x20-\x7E]') {
        throw 'An ASCII path for the game link is unavailable on this PC.'
    }

    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $pathBytes = [Text.Encoding]::UTF8.GetBytes($gameRoot.ToUpperInvariant())
        $digest = [BitConverter]::ToString($hasher.ComputeHash($pathBytes)).Replace('-', '')
    } finally {
        $hasher.Dispose()
    }

    $alias = Join-Path $aliasRoot $digest.Substring(0, 16)
    New-Item -ItemType Directory -Path $aliasRoot -Force | Out-Null
    $link = Get-Item -LiteralPath $alias -Force -ErrorAction SilentlyContinue
    if (-not $link) {
        try {
            New-Item -ItemType Junction -Path $alias -Target $gameRoot | Out-Null
        } catch {
            if (-not (Get-Item -LiteralPath $alias -Force -ErrorAction SilentlyContinue)) {
                throw
            }
        }
        $link = Get-Item -LiteralPath $alias -Force
    }
    $target = @($link.Target)[0]
    if ($link.LinkType -ne 'Junction' -or $target -ne $gameRoot) {
        throw "The game link path already points somewhere else: $alias"
    }
    $gameRoot = $alias
}

# Yu-Gi-Oh_Loader.exe resolves the game folder from Steam App 1150640's InstallLocation
# before anything else; keep HKCU pointed at the ASCII game root so mods and duel.dll load.
if ((Test-Path -LiteralPath (Join-Path $gameRoot 'YGO_2020.toc')) -and (Test-Path -LiteralPath (Join-Path $gameRoot 'YGO_2020.dat'))) {
    $uninstallKey = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 1150640'
    if (-not (Test-Path -Path $uninstallKey)) {
        New-Item -Path $uninstallKey -Force | Out-Null
    }
    $currentInstall = (Get-ItemProperty -Path $uninstallKey -Name InstallLocation -ErrorAction SilentlyContinue).InstallLocation
    if ($currentInstall -ne $gameRoot) {
        Set-ItemProperty -Path $uninstallKey -Name InstallLocation -Value $gameRoot -Type String
    }
}

$loaderFolder = Join-Path $gameRoot 'WolfX-1.6.1'
$loader = Join-Path $loaderFolder 'Yu-Gi-Oh_Loader.exe'
if ($PrepareOnly) {
    Write-Output $loader
    return
}
Start-Process -FilePath $loader -WorkingDirectory $loaderFolder -WindowStyle Normal

# Move the game window to fit Virtual Display (DISPLAY21) exactly and bring to foreground
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class WinMove {
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}
"@ -ErrorAction SilentlyContinue

Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue

for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $ygo = Get-Process -Name "YuGiOh" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }
    if ($ygo) {
        $targetScreen = [System.Windows.Forms.Screen]::PrimaryScreen
        if ($targetScreen) {
            $x = $targetScreen.Bounds.X + [Math]::Max(0, ($targetScreen.Bounds.Width - 1920) / 2)
            $y = $targetScreen.Bounds.Y + [Math]::Max(0, ($targetScreen.Bounds.Height - 1080) / 2)
            [WinMove]::SetWindowPos($ygo.MainWindowHandle, [IntPtr]::Zero, $x, $y, 1920, 1080, 0x0040)
        } else {
            [WinMove]::SetWindowPos($ygo.MainWindowHandle, [IntPtr]::Zero, 0, 0, 1920, 1080, 0x0040)
        }
        [WinMove]::ShowWindowAsync($ygo.MainWindowHandle, 9) | Out-Null
        [WinMove]::SetForegroundWindow($ygo.MainWindowHandle) | Out-Null
        break
    }
}
