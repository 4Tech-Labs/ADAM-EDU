param(
    [ValidateSet("both", "codex", "claude")]
    [string]$RuntimeHost = "both"
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Get-BashPath {
    $paths = @(
        "C:\Program Files\Git\bin\bash.exe",
        "C:\Program Files\Git\usr\bin\bash.exe"
    )
    $bashCommand = Get-Command bash -ErrorAction SilentlyContinue
    if ($bashCommand) {
        $paths += $bashCommand.Source
    }

    foreach ($candidate in $paths | Select-Object -Unique) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) {
            continue
        }

        try {
            $probe = & $candidate -lc "printf ok" 2>$null
            if ($LASTEXITCODE -eq 0 -and $probe -eq "ok") {
                return $candidate
            }
        }
        catch {
            continue
        }
    }

    throw "Git Bash is required on Windows to run gstack setup. Install Git for Windows or make bash available on PATH."
}

function Convert-ToGitBashPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)

    $resolved = (Resolve-Path -LiteralPath $WindowsPath).Path
    if ($resolved -notmatch '^(?<drive>[A-Za-z]):(?<rest>.*)$') {
        throw "Cannot convert path for Git Bash: $WindowsPath"
    }

    $drive = $Matches.drive.ToLowerInvariant()
    $rest = $Matches.rest -replace '\\', '/'
    return "/$drive$rest"
}

function Remove-PathIfExists {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    Remove-PathIfExists -Path $Destination
    $parent = Split-Path -Parent $Destination
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function Test-GitCommitPresent {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryPath,
        [Parameter(Mandatory = $true)][string]$Commit
    )

    & git -C $RepositoryPath rev-parse --verify "$Commit^{commit}" *> $null
    return $LASTEXITCODE -eq 0
}

function Clone-GstackRepo {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryUrl,
        [Parameter(Mandatory = $true)][string]$Ref,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $parent = Split-Path -Parent $Destination
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    & git clone --single-branch --branch $Ref --depth 1 $RepositoryUrl $Destination | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to clone gstack into $Destination"
    }
}

function Ensure-GstackRepoAtCommit {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryUrl,
        [Parameter(Mandatory = $true)][string]$Ref,
        [Parameter(Mandatory = $true)][string]$Commit,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $gitDir = Join-Path $Destination ".git"
    if ((Test-Path -LiteralPath $Destination) -and -not (Test-Path -LiteralPath $gitDir)) {
        Remove-PathIfExists -Path $Destination
    }

    if (-not (Test-Path -LiteralPath $gitDir)) {
        Clone-GstackRepo -RepositoryUrl $RepositoryUrl -Ref $Ref -Destination $Destination
    }
    else {
        $origin = (& git -C $Destination remote get-url origin 2>$null).Trim()
        if ($LASTEXITCODE -ne 0 -or $origin -ne $RepositoryUrl) {
            Remove-PathIfExists -Path $Destination
            Clone-GstackRepo -RepositoryUrl $RepositoryUrl -Ref $Ref -Destination $Destination
        }
    }

    $currentCommit = (& git -C $Destination rev-parse HEAD).Trim()
    if ($currentCommit -ne $Commit) {
        & git -C $Destination fetch --depth 1 origin $Ref | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to fetch gstack ref '$Ref'"
        }

        if (-not (Test-GitCommitPresent -RepositoryPath $Destination -Commit $Commit)) {
            & git -C $Destination fetch --depth 1 origin $Commit | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to fetch pinned gstack commit '$Commit'"
            }
        }

        & git -C $Destination checkout --force --detach $Commit | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to checkout pinned gstack commit '$Commit'"
        }

        & git -C $Destination clean -fdx | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to clean gstack runtime at $Destination"
        }
    }
}

function Clear-CodexRuntime {
    param([Parameter(Mandatory = $true)][string]$SkillsRoot)

    New-Item -ItemType Directory -Path $SkillsRoot -Force | Out-Null
    Get-ChildItem -LiteralPath $SkillsRoot -Force -Filter "gstack-*" | ForEach-Object {
        Remove-PathIfExists -Path $_.FullName
    }
}

function Clear-ClaudeRuntime {
    param([Parameter(Mandatory = $true)][string]$SkillsRoot)

    Remove-PathIfExists -Path $SkillsRoot
    New-Item -ItemType Directory -Path $SkillsRoot -Force | Out-Null
}

function Invoke-GstackSetup {
    param(
        [Parameter(Mandatory = $true)][string]$RuntimePath,
        [Parameter(Mandatory = $true)][string]$TargetHost
    )

    $bashPath = Convert-ToGitBashPath -WindowsPath $RuntimePath
    & $BashExe -lc "cd '$bashPath' && ./setup --host '$TargetHost'"
    if ($LASTEXITCODE -ne 0) {
        throw "gstack setup failed for host '$TargetHost'"
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LockPath = Join-Path $RepoRoot "scripts\agents\gstack.lock.json"
$AdamSkillRoot = Join-Path $RepoRoot ".agents\skills\adam-orchestrator"
$CodexSkillsRoot = Join-Path $RepoRoot ".agents\skills"
$ClaudeSkillsRoot = Join-Path $RepoRoot ".claude\skills"

Require-Command -Name "git"
if (-not (Test-Path -LiteralPath $LockPath)) {
    throw "gstack lock file not found at $LockPath"
}
if (-not (Test-Path -LiteralPath $AdamSkillRoot)) {
    throw "Tracked adam-orchestrator skill not found at $AdamSkillRoot"
}

$Lock = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
$BashExe = Get-BashPath

if ($RuntimeHost -in @("both", "codex")) {
    Clear-CodexRuntime -SkillsRoot $CodexSkillsRoot
    $codexGstackRoot = Join-Path $CodexSkillsRoot "gstack"
    Ensure-GstackRepoAtCommit -RepositoryUrl $Lock.repository -Ref $Lock.ref -Commit $Lock.commit -Destination $codexGstackRoot
    Invoke-GstackSetup -RuntimePath $codexGstackRoot -TargetHost "codex"
}

if ($RuntimeHost -in @("both", "claude")) {
    Clear-ClaudeRuntime -SkillsRoot $ClaudeSkillsRoot
    $claudeGstackRoot = Join-Path $ClaudeSkillsRoot "gstack"
    Ensure-GstackRepoAtCommit -RepositoryUrl $Lock.repository -Ref $Lock.ref -Commit $Lock.commit -Destination $claudeGstackRoot
    Invoke-GstackSetup -RuntimePath $claudeGstackRoot -TargetHost "claude"
    Copy-Tree -Source $AdamSkillRoot -Destination (Join-Path $ClaudeSkillsRoot "adam-orchestrator")
}

Write-Host "Agent bootstrap complete."
Write-Host "  repo root: $RepoRoot"
Write-Host "  host(s):   $RuntimeHost"
Write-Host "Restart Codex or Claude if the current session had already loaded skills."
