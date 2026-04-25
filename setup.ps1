#Requires -Version 5.1
<#
.SYNOPSIS
    Windows setup for Pixoo 16x16 Bluetooth control.
.DESCRIPTION
    1. Checks Python version, creates a virtual environment, installs
       required packages, and verifies the Bluetooth adapter is present.
    2. Scans Windows Bluetooth devices for a paired Pixoo/Divoom.
    3. Saves the MAC address to pixoo_config.json when a matching device is found.
    Run this script once to prepare the environment, then pair the Pixoo in
    Windows Bluetooth settings and run it again to save the device config.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status($msg)  { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)    { Write-Host "[-] $msg" -ForegroundColor Red }

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $projectDir "pixoo_config.json"

# Verify pixoo_config.json can be written before doing the rest of the work.
if (Test-Path $configPath) {
    try {
        [System.IO.File]::OpenWrite($configPath).Close()
    } catch {
        Write-Fail "$configPath exists but cannot be written ($($_.Exception.Message))."
        exit 1
    }
} else {
    try {
        $probe = Join-Path $projectDir ".pixoo_writability_probe"
        [System.IO.File]::WriteAllText($probe, "")
        Remove-Item $probe -ErrorAction SilentlyContinue
    } catch {
        Write-Fail "Project directory $projectDir is not writable; cannot save pixoo_config.json there."
        exit 1
    }
}

function Get-PairedBluetoothDevices {
    $btRegPath = "HKLM:\SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
    $devices = @()
    if (-not (Test-Path $btRegPath)) {
        Write-Warn "Bluetooth registry path not found: $btRegPath"
        Write-Warn "This script reads paired devices from the BTHPORT registry, which may not be present on every Windows SKU. Falling back to PnP enumeration only."
        return $devices
    }
    Get-ChildItem $btRegPath -ErrorAction SilentlyContinue | ForEach-Object {
            $nameBytes = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).Name
            if ($nameBytes) {
                $deviceName = [System.Text.Encoding]::UTF8.GetString($nameBytes).TrimEnd([char]0)
                $rawMac = $_.PSChildName
                $mac = ($rawMac -replace '(.{2})', '$1:').TrimEnd(':').ToUpper()
                $devices += [PSCustomObject]@{
                    Name = $deviceName
                    MAC  = $mac
                }
            }
        }
    return $devices
}

function Get-PnpBluetoothDevices {
    $devices = @()
    Get-PnpDevice -Class "Bluetooth" -Status "OK" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.FriendlyName -match "(?i)pixoo|divoom") {
            if ($_.InstanceId -match '([0-9A-Fa-f]{12})$') {
                $rawMac = $Matches[1]
                $mac = ($rawMac -replace '(.{2})', '$1:').TrimEnd(':').ToUpper()
            } else {
                $mac = "UNKNOWN"
            }
            $devices += [PSCustomObject]@{
                Name = $_.FriendlyName
                MAC  = $mac
            }
        }
    }
    return $devices
}

function Find-PixooDevices($allDevices) {
    return @($allDevices | Where-Object { $_.Name -match "(?i)pixoo|divoom" })
}

function Save-Config($mac, $name) {
    $config = @{
        mac_address = $mac
        device_name = $name
        bt_port     = 1
    } | ConvertTo-Json -Depth 2
    [System.IO.File]::WriteAllText($configPath, $config, (New-Object System.Text.UTF8Encoding $false))
    Write-Ok "Configuration saved to pixoo_config.json"
}

function Select-Device($devices, $prompt) {
    if ($devices.Count -eq 0) {
        return $null
    }

    if ($devices.Count -eq 1) {
        return $devices[0]
    }

    Write-Host ""
    for ($i = 0; $i -lt $devices.Count; $i++) {
        Write-Host "  [$($i+1)] $($devices[$i].Name)  -  MAC: $($devices[$i].MAC)"
    }
    Write-Host ""

    $choice = Read-Host $prompt
    if ($choice -notmatch '^\d+$') {
        Write-Fail "Invalid selection."
        return $null
    }

    $idx = [int]$choice - 1
    if ($idx -lt 0 -or $idx -ge $devices.Count) {
        Write-Fail "Invalid selection."
        return $null
    }

    return $devices[$idx]
}

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

# ── 6. Scan paired devices and save config if possible ─────────────
Write-Host ""
Write-Host "=== Pixoo Device Detection ===" -ForegroundColor White
Write-Host ""

Write-Status "Scanning for paired Pixoo/Divoom devices..."
[array]$allPaired = Get-PairedBluetoothDevices
[array]$pixooDevices = Find-PixooDevices $allPaired

$pnpDevices = Get-PnpBluetoothDevices
foreach ($device in $pnpDevices) {
    if (-not ($pixooDevices | Where-Object { $_.MAC -eq $device.MAC })) {
        $pixooDevices += $device
    }
}
[array]$pixooDevices = $pixooDevices

if ($pixooDevices.Count -gt 0) {
    Write-Ok "Found $($pixooDevices.Count) Pixoo/Divoom device(s)."
    if ($pixooDevices.Count -gt 1) {
        Write-Warn "Multiple devices matched 'Pixoo' or 'Divoom'. Picking the wrong MAC will fail silently when connecting -- confirm the right device below."
    }
    $selected = Select-Device $pixooDevices "Select device number (1-$($pixooDevices.Count))"
    if (-not $selected) {
        exit 1
    }

    Write-Ok "Using: $($selected.Name) ($($selected.MAC))"
    Save-Config $selected.MAC $selected.Name
    Write-Host ""
    Write-Ok "Setup complete. You can now run:  .\.venv\Scripts\python.exe test_pixoo.py"
    exit 0
}

Write-Warn "No Pixoo/Divoom device found among paired Bluetooth devices."

if ($allPaired.Count -gt 0) {
    Write-Host ""
    Write-Status "All paired Bluetooth devices:"
    foreach ($device in $allPaired) {
        Write-Host "    $($device.Name)  -  MAC: $($device.MAC)"
    }
    Write-Host ""

    $manualChoice = Read-Host "Is your Pixoo listed above under a different name? (y/n)"
    if ($manualChoice -match '^(?i)y(?:es)?$') {
        $selected = Select-Device $allPaired "Select device number (1-$($allPaired.Count))"
        if (-not $selected) {
            exit 1
        }

        Save-Config $selected.MAC $selected.Name
        Write-Host ""
        Write-Ok "Setup complete. You can now run:  .\.venv\Scripts\python.exe test_pixoo.py"
        exit 0
    }
}

Write-Host ""
Write-Status "Opening Windows Bluetooth Settings..."
Write-Host "  1. Turn ON your Pixoo device"
Write-Host "  2. In the Settings window, click 'Add device' or 'Add Bluetooth or other device'"
Write-Host "  3. Select 'Bluetooth' and pair the Pixoo"
Write-Host "  4. Re-run .\setup.ps1 after pairing so the config can be saved"
Write-Host ""

Start-Process "ms-settings:bluetooth"

# ── Done ────────────────────────────────────────────────────────────
Write-Host ""
Write-Ok "Setup complete. Next steps:"
Write-Host "  1. Pair your Pixoo in Windows Bluetooth settings"
Write-Host "  2. Run .\setup.ps1 again to save pixoo_config.json"
Write-Host "  3. Run .\.venv\Scripts\python.exe test_pixoo.py to test the connection"
