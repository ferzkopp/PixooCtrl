#Requires -Version 5.1
<#
.SYNOPSIS
    Prerequisites setup for Pixoo 16x16 Bluetooth control.
.DESCRIPTION
    Checks Python version, creates a virtual environment, installs
    required packages, and verifies the Bluetooth adapter is present.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status($msg)  { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)    { Write-Host "[-] $msg" -ForegroundColor Red }

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── 1. Check Python ────────────────────────────────────────────────
Write-Status "Checking Python installation..."
$pythonCmd = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 9) {
                $pythonCmd = $candidate
                Write-Ok "Found $ver (>= 3.9 required for socket.AF_BLUETOOTH)"
                break
            } else {
                Write-Warn "$ver found but Python >= 3.9 is required"
            }
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Fail "Python >= 3.9 not found. Install from https://www.python.org/downloads/"
    exit 1
}

# ── 2. Create virtual environment ──────────────────────────────────
$venvDir = Join-Path $projectDir ".venv"
if (-not (Test-Path $venvDir)) {
    Write-Status "Creating virtual environment in .venv ..."
    & $pythonCmd -m venv $venvDir
    Write-Ok "Virtual environment created"
} else {
    Write-Ok "Virtual environment already exists"
}

# Activate and use venv pip
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip    = Join-Path $venvDir "Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Fail "venv python not found at $venvPython"
    exit 1
}

# ── 3. Install Python packages ─────────────────────────────────────
Write-Status "Installing required Python packages..."
$ErrorActionPreference = "Continue"
& $venvPip install --upgrade pip --quiet 2>&1 | Out-Null
& $venvPip install Pillow --quiet 2>&1 | Out-Null
$ErrorActionPreference = "Stop"
Write-Ok "Pillow installed"

# ── 4. Verify socket.AF_BLUETOOTH is available ─────────────────────
Write-Status "Verifying Bluetooth socket support in Python..."
$btCheck = & $venvPython -c "import socket; print(hasattr(socket, 'AF_BLUETOOTH'))" 2>&1
if ($btCheck -eq "True") {
    Write-Ok "socket.AF_BLUETOOTH is available"
} else {
    Write-Warn "socket.AF_BLUETOOTH not available in this Python build."
    Write-Warn "Bluetooth connections may not work. Consider reinstalling Python 3.9+ from python.org."
}

# ── 5. Check Bluetooth adapter ─────────────────────────────────────
Write-Status "Checking Bluetooth adapter..."
$btAdapter = Get-PnpDevice -Class "Bluetooth" -ErrorAction SilentlyContinue |
    Where-Object { $_.FriendlyName -match "Bluetooth" -and $_.Status -eq "OK" } |
    Select-Object -First 1

if ($btAdapter) {
    Write-Ok "Bluetooth adapter found: $($btAdapter.FriendlyName)"
} else {
    # Check if adapter exists but is disabled
    $btDisabled = Get-PnpDevice -Class "Bluetooth" -ErrorAction SilentlyContinue |
        Where-Object { $_.FriendlyName -match "Bluetooth" } |
        Select-Object -First 1
    if ($btDisabled) {
        Write-Warn "Bluetooth adapter found but status is: $($btDisabled.Status)"
        Write-Warn "Enable it in Device Manager or Windows Settings."
    } else {
        Write-Fail "No Bluetooth adapter detected. A Bluetooth adapter is required."
    }
}

# ── 6. Check for already-paired Pixoo ──────────────────────────────
Write-Status "Checking for already-paired Divoom/Pixoo devices..."
$btRegPath = "HKLM:\SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
$found = $false
if (Test-Path $btRegPath) {
    Get-ChildItem $btRegPath -ErrorAction SilentlyContinue | ForEach-Object {
        $nameBytes = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).Name
        if ($nameBytes) {
            $deviceName = [System.Text.Encoding]::UTF8.GetString($nameBytes).TrimEnd([char]0)
            if ($deviceName -match "(?i)pixoo|divoom") {
                $rawMac = $_.PSChildName
                $mac = ($rawMac -replace '(.{2})', '$1:').TrimEnd(':')
                Write-Ok "Found paired device: $deviceName  (MAC: $mac)"
                $found = $true
            }
        }
    }
}
if (-not $found) {
    Write-Warn "No paired Pixoo/Divoom device found yet. Run find_and_pair_pixoo.ps1 next."
}

# ── Done ────────────────────────────────────────────────────────────
Write-Host ""
Write-Ok "Setup complete. Next steps:"
Write-Host "  1. Run .\find_and_pair_pixoo.ps1    to discover and pair your Pixoo"
Write-Host "  2. Run .\.venv\Scripts\python.exe test_pixoo.py   to test the connection"
