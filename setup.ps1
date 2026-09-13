<#
.SYNOPSIS
    Rail setup and configuration script for Windows PowerShell.

.DESCRIPTION
    Ensures ~/.rail/workflows exists, seeds the three official default workflows
    without overwriting user-edited copies, installs Rail, and prints MCP stdio
    configuration guidance.

    The script supports both local execution from a cloned Rail repository and
    remote execution through:

        irm https://raw.githubusercontent.com/yosef-atta/rail/main/setup.ps1 | iex
#>

[CmdletBinding()]
param (
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$repoOwner = "yosef-atta"
$repoName = "rail"
$repoBranch = "main"
$repoGitUrl = "git+https://github.com/$repoOwner/$repoName.git"
$rawBaseUrl = "https://raw.githubusercontent.com/$repoOwner/$repoName/$repoBranch"

$scriptPath = $MyInvocation.MyCommand.Path
$isLocalRepoExecution = $false
$scriptDir = $null

if ($scriptPath -and (Test-Path -LiteralPath $scriptPath)) {
    $scriptDir = Split-Path -Parent $scriptPath
    $isLocalRepoExecution = Test-Path -LiteralPath (Join-Path $scriptDir "pyproject.toml")
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "         Rail Setup & Configuration      " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

$userProfile = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::UserProfile)
$railHome = Join-Path $userProfile ".rail"
$workflowsDir = Join-Path $railHome "workflows"
$defaultWorkflowFiles = @(
    "default-agent.yml",
    "default-agent-github.yml",
    "default-human.yml"
)

Write-Host "`n[1/4] Ensuring global workflows directory exists..." -ForegroundColor Yellow
if (-not (Test-Path -LiteralPath $workflowsDir)) {
    New-Item -Path $workflowsDir -ItemType Directory -Force | Out-Null
    Write-Host "  Created: $workflowsDir" -ForegroundColor Green
} else {
    Write-Host "  Found:   $workflowsDir" -ForegroundColor Green
}

Write-Host "`n[2/4] Seeding official default workflows..." -ForegroundColor Yellow
foreach ($workflowFile in $defaultWorkflowFiles) {
    $destinationPath = Join-Path $workflowsDir $workflowFile

    if (Test-Path -LiteralPath $destinationPath) {
        Write-Host "  $workflowFile already exists (preserving)" -ForegroundColor Gray
        continue
    }

    if ($isLocalRepoExecution) {
        $sourcePath = Join-Path (Join-Path $scriptDir "workflows") $workflowFile
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            throw "Bundled workflow is missing: $sourcePath"
        }
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
    } else {
        $workflowUrl = "$rawBaseUrl/workflows/$workflowFile"
        Invoke-WebRequest -UseBasicParsing -Uri $workflowUrl -OutFile $destinationPath
    }

    Write-Host "  Seeded $workflowFile" -ForegroundColor Green
}

Write-Host "`n[3/4] Installing / verifying Rail CLI..." -ForegroundColor Yellow
if ($SkipInstall) {
    Write-Host "  Skipping package installation as requested." -ForegroundColor Gray
} elseif (Get-Command "uv" -ErrorAction SilentlyContinue) {
    if ($isLocalRepoExecution) {
        Write-Host "  Installing Rail as an editable uv tool from $scriptDir..." -ForegroundColor Gray
        & uv tool install --editable $scriptDir --force
    } else {
        Write-Host "  Installing Rail from GitHub with uv..." -ForegroundColor Gray
        & uv tool install $repoGitUrl --force
    }

    if ($LASTEXITCODE -ne 0) {
        throw "uv tool install failed with exit code $LASTEXITCODE"
    }
    Write-Host "  Installed Rail CLI via uv." -ForegroundColor Green
} elseif (Get-Command "pip" -ErrorAction SilentlyContinue) {
    if ($isLocalRepoExecution) {
        Write-Host "  Installing Rail with pip from $scriptDir..." -ForegroundColor Gray
        & pip install -e $scriptDir
    } else {
        Write-Host "  Installing Rail from GitHub with pip..." -ForegroundColor Gray
        & pip install $repoGitUrl
    }

    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed with exit code $LASTEXITCODE"
    }
    Write-Host "  Installed Rail CLI via pip." -ForegroundColor Green
} else {
    throw "Neither uv nor pip was found in PATH. Install Python tooling or rerun with -SkipInstall."
}

Write-Host "`n[4/4] MCP setup guidance" -ForegroundColor Yellow
Write-Host "---------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "Rail MCP uses stdio." -ForegroundColor White
Write-Host "Command: rail" -ForegroundColor White
Write-Host "Args:    serve" -ForegroundColor White
Write-Host ""
Write-Host "Example JSON configuration:" -ForegroundColor Cyan
$mcpJson = @'
{
  "mcpServers": {
    "rail": {
      "command": "rail",
      "args": ["serve"]
    }
  }
}
'@
Write-Host $mcpJson -ForegroundColor White

Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Available verification commands:" -ForegroundColor Cyan
Write-Host "  rail workflows" -ForegroundColor White
Write-Host "  rail validate default-agent" -ForegroundColor White
Write-Host "  rail validate default-agent-github" -ForegroundColor White
Write-Host "  rail validate default-human" -ForegroundColor White
Write-Host "=========================================" -ForegroundColor Cyan
