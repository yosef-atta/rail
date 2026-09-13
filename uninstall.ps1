<#
.SYNOPSIS
    Completely uninstall Rail on Windows PowerShell.

.DESCRIPTION
    Removes the Rail CLI/tool installation and deletes the global ~/.rail directory,
    including workflows and runtime state. The script does not edit MCP client
    configuration because setup.ps1 only prints MCP guidance and does not modify it.
#>

[CmdletBinding()]
param ()

$ErrorActionPreference = "Stop"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "              Rail Uninstall             " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

$userProfile = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::UserProfile)
$railHome = Join-Path $userProfile ".rail"
$removedPackage = $false

Write-Host "`n[1/2] Removing Rail CLI..." -ForegroundColor Yellow

if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    & uv tool uninstall rail 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Removed Rail uv tool installation." -ForegroundColor Green
        $removedPackage = $true
    }
}

if (-not $removedPackage) {
    $pythonCommand = Get-Command "python" -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & python -m pip uninstall -y rail 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Removed Rail pip installation." -ForegroundColor Green
            $removedPackage = $true
        }
    } elseif (Get-Command "pip" -ErrorAction SilentlyContinue) {
        & pip uninstall -y rail 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Removed Rail pip installation." -ForegroundColor Green
            $removedPackage = $true
        }
    }
}

if (-not $removedPackage) {
    Write-Host "  Rail package was not found through uv or pip." -ForegroundColor Gray
}

Write-Host "`n[2/2] Removing global Rail data..." -ForegroundColor Yellow
if (Test-Path -LiteralPath $railHome) {
    Remove-Item -LiteralPath $railHome -Recurse -Force
    Write-Host "  Removed: $railHome" -ForegroundColor Green
} else {
    Write-Host "  Global Rail directory was not present: $railHome" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Rail uninstall complete." -ForegroundColor Green
Write-Host ""
Write-Host "Note: MCP client configuration was not modified." -ForegroundColor Gray
Write-Host "If you manually added a Rail MCP entry, remove that entry from your MCP client config." -ForegroundColor Gray
Write-Host "=========================================" -ForegroundColor Cyan
