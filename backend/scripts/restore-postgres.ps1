param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,

    [Parameter(Mandatory = $false)]
    [string]$TargetDatabase = $env:RESTORE_PGDATABASE
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($TargetDatabase)) {
    throw "Specify -TargetDatabase or set the RESTORE_PGDATABASE environment variable to the temporary drill database."
}

if (-not (Test-Path -LiteralPath $BackupFile)) {
    throw "Backup archive file not found: $BackupFile"
}

$liveDb = [Environment]::GetEnvironmentVariable("PGDATABASE")
if (-not [string]::IsNullOrWhiteSpace($liveDb) -and ($TargetDatabase.Trim().ToLowerInvariant() -eq $liveDb.Trim().ToLowerInvariant())) {
    throw "Target database '$TargetDatabase' matches the live PGDATABASE setting. Refusing to restore over the live database."
}

$requiredVariables = @("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD")
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

$pgRestorePath = Resolve-PgTool "pg_restore"
if (-not $pgRestorePath) {
    throw "Install PostgreSQL client tools so pg_restore is available."
}

# Verify SHA-256 sidecar if present
$checksumFile = "$BackupFile.sha256"
if (Test-Path -LiteralPath $checksumFile) {
    $expectedLine = (Get-Content -LiteralPath $checksumFile -Encoding ascii | Select-Object -First 1).Trim()
    $expectedHash = ($expectedLine -split "\s+")[0].ToLowerInvariant()
    $actualHash = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expectedHash -ne $actualHash) {
        throw "SHA-256 verification failed for $BackupFile. Expected: $expectedHash, Actual: $actualHash"
    }
    Write-Output "Verified SHA-256 integrity: $actualHash"
}

Write-Output "Restoring archive to isolated database '$TargetDatabase'..."
& $pgRestorePath --no-owner --dbname $TargetDatabase $BackupFile
if ($LASTEXITCODE -ne 0) {
    throw "pg_restore exited with error code $LASTEXITCODE."
}

Write-Output "Restore drill completed successfully for database '$TargetDatabase'."
Write-Output "Run verification checks (python manage.py check, tests, and financial reconciliation report) against this database."

