param(
    [string]$BackupDirectory = $env:SERVICEFLOW_BACKUP_DIR
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
    throw "Set SERVICEFLOW_BACKUP_DIR to an approved encrypted backup directory."
}

$requiredVariables = @("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
foreach ($name in $requiredVariables) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "The required PostgreSQL environment variable $name is not configured."
    }
}

function Resolve-PgTool {
    param([string]$toolName)
    $cmd = Get-Command $toolName -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $candidates = @(
        "$env:ProgramFiles\PostgreSQL\*\bin",
        "${env:ProgramFiles(x86)}\PostgreSQL\*\bin",
        "$env:LOCALAPPDATA\Programs\PostgreSQL\*\bin"
    )
    foreach ($pattern in $candidates) {
        $found = Get-Item (Join-Path $pattern "$toolName.exe") -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }
    return $null
}

$pgDumpPath = Resolve-PgTool "pg_dump"
$pgRestorePath = Resolve-PgTool "pg_restore"
if (-not $pgDumpPath -or -not $pgRestorePath) {
    throw "Install PostgreSQL client tools so pg_dump and pg_restore are available."
}

$projectRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..\..")
).TrimEnd("\") + "\"
$resolvedDirectory = [System.IO.Path]::GetFullPath($BackupDirectory).TrimEnd("\") + "\"
if ($resolvedDirectory.StartsWith(
        $projectRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Backups must not be written inside the ServiceFlow project directory."
}

New-Item -ItemType Directory -Path $resolvedDirectory -Force | Out-Null
$timestamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmssfff")
$fileName = "serviceflow-$timestamp.dump"
$partialFile = Join-Path $resolvedDirectory "$fileName.partial"
$backupFile = Join-Path $resolvedDirectory $fileName
$checksumFile = "$backupFile.sha256"

& $pgDumpPath --format=custom --no-owner --file $partialFile --dbname $env:PGDATABASE
if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE. Partial output was not promoted."
}

& $pgRestorePath --list $partialFile | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "pg_restore could not read the generated archive. Partial output was not promoted."
}

Move-Item -LiteralPath $partialFile -Destination $backupFile
$hash = (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $fileName" | Set-Content -LiteralPath $checksumFile -Encoding ascii

Write-Output "Verified PostgreSQL archive: $backupFile"
Write-Output "SHA-256: $hash"
