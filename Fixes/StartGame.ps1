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

$loaderFolder = Join-Path $gameRoot 'WolfX-1.6.1'
$loader = Join-Path $loaderFolder 'Yu-Gi-Oh_Loader.exe'
if ($PrepareOnly) {
    Write-Output $loader
    return
}
Start-Process -FilePath $loader -WorkingDirectory $loaderFolder -WindowStyle Normal
