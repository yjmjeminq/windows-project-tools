param(
    [string]$KeyFile,
    [string]$BundleDirectory,
    [switch]$PCUpdateOnly
)

$ErrorActionPreference = 'Stop'
$project = (Get-Item -LiteralPath $PSScriptRoot).FullName
$ryujinxPath = 'ryujinx-1.3.3-win_x64/publish'
$titleId = '010022400be5a000'
$environmentRoot = Join-Path $env:LOCALAPPDATA 'YGO-PC-Full/Environment/windows-v1'
$releaseUrl = 'https://github.com/yjmjeminq/windows-project-environment/releases/download/windows-v1'
$manifestSha256 = 'a951907c3e212965b431d980e16a0d56091a76c4d4809343f3c7a7e97c3817f7'
$pcUpdate = @{
    name = 'pc-update-2026-11-12.age'
    sha256 = '8f889343d51398480e7640478e293736e64e7cbbd08de5980fadd4c12272ad39'
    bytes = 235946344
    files = 4189
}

function Receive-ReleaseFile($Uri, $Destination) {
    $partial = "$Destination.download"
    try {
        & curl.exe -q --proto '=https' --proto-redir '=https' --location --fail --silent --show-error --retry 3 --connect-timeout 20 --output $partial $Uri
        if ($LASTEXITCODE -ne 0) { throw "GitHub download failed for $([IO.Path]::GetFileName($Destination))." }
        Move-Item -LiteralPath $partial -Destination $Destination -Force
    } finally {
        if ([IO.File]::Exists($partial)) { [IO.File]::Delete($partial) }
    }
}

function Test-EnvironmentPart($Path, $Part) {
    $file = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    return ($file -and $file.Length -eq [long]$Part.bytes -and
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Part.sha256)
}

function Get-AgeExecutable($Stage) {
    $folder = Join-Path $environmentRoot 'age-v1.3.2'
    $path = Join-Path $folder 'age.exe'
    $exeSha256 = '2821a4ed191da07372acd302e5f6feae7a7985e285e1417765ebe74025af45f0'
    if ([IO.File]::Exists($path) -and (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -eq $exeSha256) {
        return $path
    }
    $download = Join-Path $Stage 'age.zip'
    $uri = 'https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-windows-amd64.zip'
    Receive-ReleaseFile $uri $download
    if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne 'f48d8f8f9ebe903ab5027ed067652f2cc1db94bc206976430133b905dcd8e8c7') {
        throw 'Could not download the verified age release.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($download)
    $unpacked = Join-Path $Stage 'age.exe'
    try {
        $entries = @($zip.Entries | Where-Object { $_.Name -ceq 'age.exe' })
        if ($entries.Count -ne 1) { throw 'The age release is missing its executable.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entries[0], $unpacked)
    } finally { $zip.Dispose() }
    if ((Get-FileHash -LiteralPath $unpacked -Algorithm SHA256).Hash -ne $exeSha256) {
        throw 'The age executable failed verification.'
    }
    [IO.Directory]::CreateDirectory($folder) | Out-Null
    Move-Item -LiteralPath $unpacked -Destination $path -Force
    return $path
}

function Expand-EncryptedBundle($Parts, $SecretFile, $Archive, $Age) {
    $arguments = "--decrypt --identity `"$SecretFile`" --output `"$Archive`""
    $proc = [Diagnostics.Process]::new()
    $proc.StartInfo = [Diagnostics.ProcessStartInfo]::new($Age, $arguments)
    $proc.StartInfo.UseShellExecute = $false
    $proc.StartInfo.CreateNoWindow = $true
    $proc.StartInfo.RedirectStandardInput = $true
    $proc.StartInfo.RedirectStandardError = $true
    try {
        if (-not $proc.Start()) { throw 'Could not start age.' }
        $stderr = $proc.StandardError.ReadToEndAsync()
        $inputStream = $proc.StandardInput.BaseStream
        $writeError = $null
        try {
            foreach ($path in $Parts) {
                $stream = [IO.File]::OpenRead($path)
                try { $stream.CopyTo($inputStream) } finally { $stream.Dispose() }
            }
        } catch { $writeError = $_ } finally { $inputStream.Dispose() }
        $proc.WaitForExit()
        $null = $stderr.GetAwaiter().GetResult()
        if ($proc.ExitCode -ne 0) { throw 'Could not unlock the environment. Check the recovery key.' }
        if ($writeError) { throw $writeError }
    } finally { $proc.Dispose() }
}

function Install-PortableFirmware($FirmwareZip, $Portable) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($FirmwareZip)
    try {
        if ($zip.Entries.Count -ne 227) { throw 'The firmware ZIP does not contain 227 NCAs.' }
        $registered = Join-Path $Portable 'bis/system/Contents/registered'
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -cnotmatch '^[a-f0-9]{32}(\.cnmt)?\.nca$') { throw 'Unexpected firmware entry.' }
            $ncaDir = Join-Path $registered ($entry.FullName -replace '\.cnmt\.nca$', '.nca')
            [IO.Directory]::CreateDirectory($ncaDir) | Out-Null
            $target = [IO.File]::Open((Join-Path $ncaDir '00'), 'CreateNew', 'Write')
            try {
                $source = $entry.Open()
                try { $source.CopyTo($target) } finally { $source.Dispose() }
            } finally { $target.Dispose() }
        }
    } finally { $zip.Dispose() }
}

function Write-JsonFile($Path, $Data) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $content = ($Data | ConvertTo-Json -Depth 30) + "`r`n"
        [IO.File]::WriteAllText($temporary, $content, [Text.UTF8Encoding]::new($false))
        if ([IO.File]::Exists($Path)) {
            [IO.File]::Replace($temporary, $Path, [NullString]::Value)
        } else { [IO.File]::Move($temporary, $Path) }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
}

function Assert-PCEnvironment {
    $required = @(
        'YuGiOh.exe'
        'YGO_2020.dat'
        'YGO_2020.toc'
        'WolfX-1.6.1/Yu-Gi-Oh_Loader.exe'
        'WolfX-1.6.1/Plugins/Yu-Gi-Oh-Core.dll'
        'WolfX-1.6.1/Plugins/Yu-Gi-Oh-Cards.dll'
        'Mods/Master Duel Engine/duel.dll'
    )
    foreach ($relative in $required) {
        if (-not [IO.File]::Exists((Join-Path $project $relative))) {
            throw "PC installation is missing $relative. Run Setup-YGO.cmd first."
        }
    }
}

function Install-PCUpdate($BundleDirectory, $Online, $Stage, $KeyFile) {
    Assert-PCEnvironment
    $encrypted = Join-Path $BundleDirectory $pcUpdate.name
    if ($Online -and -not (Test-EnvironmentPart $encrypted $pcUpdate)) {
        Write-Host 'Downloading the PC update...'
        Receive-ReleaseFile "$releaseUrl/$($pcUpdate.name)" $encrypted
    }
    if (-not (Test-EnvironmentPart $encrypted $pcUpdate)) {
        throw "Missing or damaged PC update $($pcUpdate.name)."
    }

    Write-Host 'Applying the PC update...'
    $archive = Join-Path $Stage 'pc-update.tar.gz'
    $payload = Join-Path $Stage 'pc-update'
    Expand-EncryptedBundle @($encrypted) $KeyFile $archive (Get-AgeExecutable $Stage)
    [IO.Directory]::CreateDirectory($payload) | Out-Null
    & tar.exe -xzf $archive -C $payload
    if ($LASTEXITCODE -ne 0) { throw 'The PC update could not be extracted.' }
    [IO.File]::Delete($archive)
    $files = @(Get-ChildItem -LiteralPath $payload -File -Recurse -Force)
    if ($files.Count -ne $pcUpdate.files) { throw 'The PC update is incomplete.' }

    $modListPath = Join-Path $project 'Mods/modlist.json'
    $modList = if ([IO.File]::Exists($modListPath)) {
        Get-Content -LiteralPath $modListPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } else { [pscustomobject]@{ mods = @() } }
    if ($modList.mods -isnot [array]) { throw 'Invalid Mods/modlist.json.' }
    $managedMods = [ordered]@{
        'Master Duel Engine' = $true
        '2020-2021-Cards' = $false
        '2026-01-Cards' = $false
        '2026-11-KR-Cards' = $true
        'Anime-Sanctity' = $true
        'Korean-Readable-Font' = $true
    }
    $updatedEntries = foreach ($id in $managedMods.Keys) {
        $entry = $modList.mods | Where-Object { $_.id -eq $id } | Select-Object -First 1
        if (-not $entry) { $entry = [pscustomobject]@{ id = $id } }
        $entry | Add-Member -NotePropertyName enabled -NotePropertyValue $managedMods[$id] -Force
        $entry
    }
    $modList.mods = @($updatedEntries) + @($modList.mods | Where-Object { -not $managedMods.Contains([string]$_.id) })

    $backupRoot = Join-Path $Stage 'pc-backup'
    $changes = [Collections.Generic.Stack[object]]::new()
    try {
        foreach ($file in $files) {
            $relative = $file.FullName.Substring($payload.Length + 1)
            $destination = Join-Path $project $relative
            $backup = $null
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
            if ([IO.File]::Exists($destination)) {
                $backup = Join-Path $backupRoot $relative
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($backup)) | Out-Null
                [IO.File]::Replace($file.FullName, $destination, $backup)
            } else { [IO.File]::Move($file.FullName, $destination) }
            $changes.Push(@{ destination = $destination; backup = $backup })
        }
        Write-JsonFile $modListPath $modList
    } catch {
        foreach ($change in $changes) {
            try {
                if ($change.backup) {
                    [IO.File]::Replace($change.backup, $change.destination, [NullString]::Value)
                } else { [IO.File]::Delete($change.destination) }
            } catch {
                $script:retainStage = $true
                Write-Warning "Could not restore $($change.destination). Update backups are at $backupRoot."
            }
        }
        throw
    }
    Write-Host "PC update ready in $project"
}

[IO.Directory]::CreateDirectory($environmentRoot) | Out-Null
$lock = [IO.File]::Open((Join-Path $environmentRoot 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$stage = Join-Path $project ('.ygo-' + [guid]::NewGuid().ToString('N').Substring(0, 12))
$retainStage = $false
try {
    if ($PCUpdateOnly) { Assert-PCEnvironment }
    [IO.Directory]::CreateDirectory($stage) | Out-Null
    if (-not $KeyFile) { $KeyFile = Join-Path $environmentRoot 'environment-recovery.agekey' }
    if ([IO.File]::Exists($KeyFile)) {
        $KeyFile = (Get-Item -LiteralPath $KeyFile).FullName
        $keyText = [IO.File]::ReadAllText($KeyFile).Trim()
    } else {
        $secret = Read-Host 'Environment recovery key' -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        try { $keyText = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim() }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr); $secret.Dispose() }
        $KeyFile = Join-Path $stage 'recovery.agekey'
        [IO.File]::WriteAllText($KeyFile, $keyText, [Text.Encoding]::ASCII)
    }
    if ($keyText -cnotmatch '^AGE-SECRET-KEY-1[A-Z0-9]{58}$') { throw 'Enter the complete AGE-SECRET-KEY line from the recovery file.' }
    $keyText = $null

    $online = -not $BundleDirectory
    if ($online) {
        $BundleDirectory = Join-Path $environmentRoot 'download'
        [IO.Directory]::CreateDirectory($BundleDirectory) | Out-Null
    }
    if ($PCUpdateOnly) {
        Install-PCUpdate $BundleDirectory $online $stage $KeyFile
        return
    }
    $manifestFile = Join-Path $BundleDirectory 'environment.json'
    if ($online) { Receive-ReleaseFile "$releaseUrl/environment.json" $manifestFile }
    if ((Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash -ne $manifestSha256) {
        throw 'The environment manifest failed verification.'
    }
    $manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format -ne 1 -or $manifest.encryption -ne 'age-x25519' -or $manifest.ryujinx -ne '1.3.3' -or
        $manifest.firmware -ne '15.0.0' -or $manifest.game_update -ne '1.0.1' -or
        $manifest.files -lt 1 -or -not $manifest.parts) { throw 'Unsupported environment manifest.' }

    $number = 0
    $parts = @(
        foreach ($part in $manifest.parts) {
            $number++
            $name = 'environment-{0:000}.age.part' -f $number
            if ($part.name -cne $name -or $part.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
                $part.bytes -lt 1 -or $part.bytes -gt 268435456) { throw 'Invalid environment manifest entry.' }
            $path = Join-Path $BundleDirectory $name
            if (-not (Test-EnvironmentPart $path $part)) {
                if (-not $online) { throw "Missing or damaged environment part $name." }
                Write-Host "Downloading $number / $($manifest.parts.Count)"
                Receive-ReleaseFile "$releaseUrl/$name" $path
                if (-not (Test-EnvironmentPart $path $part)) { throw "Checksum failed for $name." }
            }
            $path
        }
    )
    Write-Host 'Unlocking and unpacking the environment...'
    $age = Get-AgeExecutable $stage
    $archive = Join-Path $stage 'environment.tar.gz'
    Expand-EncryptedBundle $parts $KeyFile $archive $age
    $payload = Join-Path $stage 'files'
    [IO.Directory]::CreateDirectory($payload) | Out-Null
    & tar.exe -xzf $archive -C $payload
    if ($LASTEXITCODE -ne 0) { throw 'The environment archive could not be extracted.' }
    [IO.File]::Delete($archive)
    if (@(Get-ChildItem -LiteralPath $payload -File -Recurse -Force).Count -ne $manifest.files) {
        throw 'The extracted environment does not match its manifest.'
    }

    $portable = Join-Path (Join-Path $payload $ryujinxPath) 'portable'
    $system = Join-Path $portable 'system'
    [IO.Directory]::CreateDirectory($system) | Out-Null
    [IO.File]::Copy((Join-Path $payload 'Keys 15.0.0/prod.keys'), (Join-Path $system 'prod.keys'))
    Install-PortableFirmware (Join-Path $payload 'Firmware 15.0.0.zip') $portable
    $updates = @(Get-ChildItem -LiteralPath $payload -File -Filter '*010022400BE5A800*.nsp')
    if ($updates.Count -ne 1) { throw 'The expected Switch update NSP was not found.' }

    foreach ($file in Get-ChildItem -LiteralPath $payload -File -Recurse -Force) {
        $relative = $file.FullName.Substring($payload.Length + 1)
        $destination = Join-Path $project $relative
        if (-not [IO.File]::Exists($destination)) {
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
            [IO.File]::Move($file.FullName, $destination)
        }
    }

    $portable = Join-Path (Join-Path $project $ryujinxPath) 'portable'
    $configPath = Join-Path $portable 'Config.json'
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $config.game_dirs = @($project) + @($config.game_dirs | Where-Object { $_ -and $_ -ne $project })
    Write-JsonFile $configPath $config
    $update = Join-Path $project $updates[0].Name
    Write-JsonFile (Join-Path $portable "games/$titleId/updates.json") @{ selected = $update; paths = @($update) }
    Write-Host "Environment ready in $project"
    if ($online -or [IO.File]::Exists((Join-Path $BundleDirectory $pcUpdate.name))) {
        Install-PCUpdate $BundleDirectory $online $stage $KeyFile
    }
} finally {
    try {
        if (-not $retainStage -and [IO.Directory]::Exists($stage)) {
            $resolved = (Resolve-Path -LiteralPath $stage).ProviderPath
            if ([IO.Path]::GetDirectoryName($resolved) -eq $project -and [IO.Path]::GetFileName($resolved) -match '^\.ygo-[a-f0-9]{12}$') {
                Remove-Item -LiteralPath $resolved -Recurse -Force
            }
        }
    } catch {
        Write-Warning "Could not clean the setup staging folder at $stage."
    } finally {
        $lock.Dispose()
    }
}
