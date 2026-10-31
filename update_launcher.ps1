param([switch]$SkipUpdate, [switch]$NoLaunch)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$game = Join-Path $root 'DragonPongClone.exe'
$versionFile = Join-Path $root 'client_version.txt'
$manifestUrl = 'https://raw.githubusercontent.com/ghostkillerr/dragonpong-clone/main/update.json'

function Read-Version([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return [version]'0.0.0' }
    $value = (Get-Content -LiteralPath $path -Raw).Trim()
    if ($value -notmatch '^\d+\.\d+\.\d+$') { throw 'Gecersiz yerel surum.' }
    return [version]$value
}

function Install-Update($manifest) {
    if ($manifest.version -notmatch '^\d+\.\d+\.\d+$') { throw 'Gecersiz guncelleme surumu.' }
    if ([version]$manifest.version -le (Read-Version $versionFile)) { return }
    $expected = [string]$manifest.sha256
    $uri = [uri]$manifest.package_url
    if ($expected -notmatch '^[a-fA-F0-9]{64}$' -or
        $uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com' -or
        -not $uri.AbsolutePath.StartsWith('/ghostkillerr/dragonpong-clone/releases/download/')) {
        throw 'Guncelleme kaynagi veya ozeti gecersiz.'
    }

    $temporary = Join-Path $root ('.update-' + [guid]::NewGuid().ToString('N'))
    $backup = Join-Path $root 'DragonPongClone.exe.previous'
    New-Item -ItemType Directory -Path $temporary | Out-Null
    try {
        $archivePath = Join-Path $temporary 'client.zip'
        Invoke-WebRequest -Uri $uri -OutFile $archivePath -TimeoutSec 30
        $actual = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
        if ($actual -ine $expected) { throw 'Guncelleme dosyasinin SHA-256 ozeti uyusmuyor.' }

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            $entry = $archive.GetEntry('DragonPongClone.exe')
            if ($null -eq $entry -or $entry.Length -le 0) { throw 'Pakette oyun EXE dosyasi yok.' }
            $staged = Join-Path $temporary 'DragonPongClone.exe'
            $inputStream = $entry.Open()
            $outputStream = [System.IO.File]::Create($staged)
            try { $inputStream.CopyTo($outputStream) }
            finally { $outputStream.Dispose(); $inputStream.Dispose() }
        }
        finally { $archive.Dispose() }

        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
        if (Test-Path -LiteralPath $game) { Move-Item -LiteralPath $game -Destination $backup }
        $oldVersion = if (Test-Path -LiteralPath $versionFile) { Get-Content -LiteralPath $versionFile -Raw } else { $null }
        try {
            Move-Item -LiteralPath $staged -Destination $game
            [System.IO.File]::WriteAllText((Join-Path $root 'client_version.txt.tmp'), [string]$manifest.version)
            Move-Item -LiteralPath (Join-Path $root 'client_version.txt.tmp') -Destination $versionFile -Force
        }
        catch {
            if (Test-Path -LiteralPath $game) { Remove-Item -LiteralPath $game -Force }
            if (Test-Path -LiteralPath $backup) {
                Move-Item -LiteralPath $backup -Destination $game
            }
            if ($null -ne $oldVersion) { [System.IO.File]::WriteAllText($versionFile, $oldVersion) }
            throw
        }
    }
    finally { Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue }
}

if (-not $SkipUpdate -and (Test-Path -LiteralPath $game)) {
    try {
        $manifest = Invoke-RestMethod -Uri $manifestUrl -TimeoutSec 5
        Install-Update $manifest
    }
    catch { Write-Warning ('Guncelleme alinamadi; mevcut oyun aciliyor: ' + $_.Exception.Message) }
}

if (-not (Test-Path -LiteralPath $game)) { throw 'DragonPongClone.exe bulunamadi.' }
if (-not $NoLaunch) { Start-Process -FilePath $game -WorkingDirectory $root }
