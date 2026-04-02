param(
    [string]$RepositoryUrl = "https://github.com/garrytan/gstack.git",
    [string]$Ref = "main"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LockPath = Join-Path $RepoRoot "scripts\agents\gstack.lock.json"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("adam-gstack-" + [guid]::NewGuid().ToString("N"))

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Required command not found: git"
}

try {
    & git clone --single-branch --branch $Ref --depth 1 $RepositoryUrl $TempRoot | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to clone gstack from $RepositoryUrl"
    }

    $commit = (& git -C $TempRoot rev-parse HEAD).Trim()
    $version = (Get-Content -LiteralPath (Join-Path $TempRoot "VERSION") -Raw).Trim()
    $updatedUtc = (Get-Date).ToUniversalTime().ToString("o")

    $lock = @"
{
  "repository": "$RepositoryUrl",
  "ref": "$Ref",
  "commit": "$commit",
  "version": "$version",
  "updated_utc": "$updatedUtc"
}
"@
    Set-Content -LiteralPath $LockPath -Value $lock -NoNewline
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}

Write-Host "Pinned gstack lock updated."
Write-Host "  repository: $RepositoryUrl"
Write-Host "  ref:        $Ref"
Write-Host "  lock:       $LockPath"
Write-Host "Run bootstrap again before validating local runtimes."
