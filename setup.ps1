param([string]$Python = "python", [switch]$InspectOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$repo = 'jungbin128/claude-pet-share'
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -Headers @{'User-Agent'='ClaudePet-Setup'}
$version = [string]$release.tag_name
if ($release.draft -or $release.prerelease -or $version -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') { throw 'Invalid release version' }
$name = "claude-pet-$version.zip"
$assets = @($release.assets | Where-Object { $_.name -eq $name })
if ($assets.Count -ne 1 -or $assets[0].digest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Missing release SHA-256' }
$asset = $assets[0]
$url = "https://github.com/$repo/releases/download/$version/$name"
if ($asset.browser_download_url -ne $url -or $asset.size -gt 83886080) { throw 'Unexpected release asset' }
$work = Join-Path ([IO.Path]::GetTempPath()) ('claude-pet-setup-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($work) | Out-Null
try {
    $zip = Join-Path $work $name
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ('sha256:' + $hash -ne $asset.digest) { throw 'Release checksum mismatch' }
    $source = Join-Path $work 'source'
    [IO.Directory]::CreateDirectory($source) | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        foreach ($entry in $archive.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $source $entry.FullName))
            if (-not $target.StartsWith($source + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe ZIP path' }
            if ($entry.FullName -match '(^|[/\\])\.\.([/\\]|$)' -or $entry.FullName.Contains(':') -or $entry.Length -gt 20971520) { throw 'Unsafe ZIP entry' }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $false)
        }
    } finally { $archive.Dispose() }
    & $Python -X utf8 -I (Join-Path $source 'install.py') --package $zip --inspect
    if ($LASTEXITCODE -ne 0) { throw 'Package validation failed' }
    if ($InspectOnly) { return }
    & $Python -X utf8 -I (Join-Path $source 'install.py') --package $zip
    if ($LASTEXITCODE -ne 0) { throw 'Setup failed' }
} finally {
    $resolved = [IO.Path]::GetFullPath($work)
    $temporary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolved.StartsWith($temporary, [StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($resolved).StartsWith('claude-pet-setup-')) {
        [IO.Directory]::Delete($resolved, $true)
    }
}
