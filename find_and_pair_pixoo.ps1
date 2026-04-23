#Requires -Version 5.1
<#
.SYNOPSIS
    Discover, pair, and save the Pixoo Bluetooth MAC address.
.DESCRIPTION
    1. Scans the Windows Bluetooth registry for already-paired Pixoo/Divoom devices.
    2. If not found, opens Windows Bluetooth Settings so the user can pair manually,
       then re-scans.
    3. Saves the MAC address to pixoo_config.json for use by the Python scripts.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)     { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn($msg)   { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)   { Write-Host "[-] $msg" -ForegroundColor Red }

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $projectDir "pixoo_config.json"

# ── Helper: scan registry for paired BT devices ───────────────────
function Get-PairedBluetoothDevices {
    $btRegPath = "HKLM:\SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
    $devices = @()
    if (Test-Path $btRegPath) {
        Get-ChildItem $btRegPath -ErrorAction SilentlyContinue | ForEach-Object {
            $nameBytes = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).Name
            if ($nameBytes) {
                $deviceName = [System.Text.Encoding]::UTF8.GetString($nameBytes).TrimEnd([char]0)
                $rawMac = $_.PSChildName
                # Registry key is 12 hex chars, e.g. "1175583a2b35"
                $mac = ($rawMac -replace '(.{2})', '$1:').TrimEnd(':').ToUpper()
                $devices += [PSCustomObject]@{
                    Name = $deviceName
                    MAC  = $mac
                }
            }
        }
    }
    return $devices
}

# ── Helper: also check PnP devices for Bluetooth entries ──────────
function Get-PnpBluetoothDevices {
    $devices = @()
    Get-PnpDevice -Class "Bluetooth" -Status "OK" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.FriendlyName -match "(?i)pixoo|divoom") {
            # Try to extract MAC from InstanceId
            # Format: BTHENUM\{...}_LOCALMFG&XXXX\Y&XXXXXXXX&X&XXXXXXXXXXXX
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

# ── Helper: find Pixoo devices from a device list ──────────────────
function Find-PixooDevices($allDevices) {
    return @($allDevices | Where-Object { $_.Name -match "(?i)pixoo|divoom" })
}

# ── Helper: save config ───────────────────────────────────────────
function Save-Config($mac, $name) {
    $config = @{
        mac_address = $mac
        device_name = $name
        bt_port     = 1
    } | ConvertTo-Json -Depth 2
    [System.IO.File]::WriteAllText($configPath, $config, (New-Object System.Text.UTF8Encoding $false))
    Write-Ok "Configuration saved to pixoo_config.json"
}

# ── Main ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Pixoo Bluetooth Discovery & Pairing ===" -ForegroundColor White
Write-Host ""

# Step 1: Scan for already-paired Pixoo devices
Write-Status "Scanning for paired Pixoo/Divoom devices..."
[array]$allPaired = Get-PairedBluetoothDevices
[array]$pixooDevices = Find-PixooDevices $allPaired

# Also check PnP
$pnpDevices = Get-PnpBluetoothDevices
foreach ($d in $pnpDevices) {
    if (-not ($pixooDevices | Where-Object { $_.MAC -eq $d.MAC })) {
        $pixooDevices += $d
    }
}
[array]$pixooDevices = $pixooDevices

if ($pixooDevices.Count -gt 0) {
    Write-Ok "Found $($pixooDevices.Count) Pixoo/Divoom device(s):"
    Write-Host ""
    for ($i = 0; $i -lt $pixooDevices.Count; $i++) {
        Write-Host "  [$($i+1)] $($pixooDevices[$i].Name)  -  MAC: $($pixooDevices[$i].MAC)"
    }
    Write-Host ""

    if ($pixooDevices.Count -eq 1) {
        $selected = $pixooDevices[0]
    } else {
        $choice = Read-Host "Select device number (1-$($pixooDevices.Count))"
        $idx = [int]$choice - 1
        if ($idx -lt 0 -or $idx -ge $pixooDevices.Count) {
            Write-Fail "Invalid selection."
            exit 1
        }
        $selected = $pixooDevices[$idx]
    }

    Write-Ok "Using: $($selected.Name) ($($selected.MAC))"
    Save-Config $selected.MAC $selected.Name
    Write-Host ""
    Write-Ok "Done! You can now run:  .\.venv\Scripts\python.exe test_pixoo.py"
    exit 0
}

# Step 2: No paired device found – show all paired BT devices for reference
Write-Warn "No Pixoo/Divoom device found among paired Bluetooth devices."
Write-Host ""

if ($allPaired.Count -gt 0) {
    Write-Status "All paired Bluetooth devices:"
    foreach ($d in $allPaired) {
        Write-Host "    $($d.Name)  -  MAC: $($d.MAC)"
    }
    Write-Host ""

    $manualChoice = Read-Host "Is your Pixoo listed above under a different name? (y/n)"
    if ($manualChoice -eq 'y') {
        Write-Host ""
        for ($i = 0; $i -lt $allPaired.Count; $i++) {
            Write-Host "  [$($i+1)] $($allPaired[$i].Name)  -  MAC: $($allPaired[$i].MAC)"
        }
        $choice = Read-Host "Select device number"
        $idx = [int]$choice - 1
        if ($idx -ge 0 -and $idx -lt $allPaired.Count) {
            $selected = $allPaired[$idx]
            Save-Config $selected.MAC $selected.Name
            Write-Ok "Done! Run:  .\.venv\Scripts\python.exe test_pixoo.py"
            exit 0
        }
    }
}

# Step 3: Open Bluetooth settings for the user to pair
Write-Host ""
Write-Status "Opening Windows Bluetooth Settings..."
Write-Host "  1. Turn ON your Pixoo device"
Write-Host "  2. In the Settings window, click 'Add Bluetooth or other device'"
Write-Host "  3. Select 'Bluetooth' and wait for 'Pixoo' to appear"
Write-Host "  4. Click on it to pair"
Write-Host ""

Start-Process "ms-settings:bluetooth"

$maxAttempts = 12
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    Write-Status "Waiting for pairing... (attempt $attempt/$maxAttempts, press Ctrl+C to cancel)"
    Start-Sleep -Seconds 10

    [array]$allPaired = Get-PairedBluetoothDevices
    [array]$pixooDevices = Find-PixooDevices $allPaired

    $pnpDevices = Get-PnpBluetoothDevices
    foreach ($d in $pnpDevices) {
        if (-not ($pixooDevices | Where-Object { $_.MAC -eq $d.MAC })) {
            $pixooDevices += $d
        }
    }
    [array]$pixooDevices = $pixooDevices

    if ($pixooDevices.Count -gt 0) {
        Write-Host ""
        Write-Ok "Pixoo device detected!"
        $selected = $pixooDevices[0]
        Write-Ok "Device: $($selected.Name)  MAC: $($selected.MAC)"
        Save-Config $selected.MAC $selected.Name
        Write-Host ""
        Write-Ok "Done! Run:  .\.venv\Scripts\python.exe test_pixoo.py"
        exit 0
    }
}

# Step 4: Manual entry as last resort
Write-Host ""
Write-Warn "Automatic detection timed out."
Write-Host ""
$manualMac = Read-Host "Enter your Pixoo's MAC address manually (format AA:BB:CC:DD:EE:FF), or press Enter to abort"
if ($manualMac -match '^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$') {
    Save-Config $manualMac.ToUpper() "Pixoo (manual)"
    Write-Ok "Done! Run:  .\.venv\Scripts\python.exe test_pixoo.py"
} else {
    if ($manualMac -ne "") {
        Write-Fail "Invalid MAC address format."
    }
    Write-Fail "No device configured. Pair your Pixoo first, then re-run this script."
    exit 1
}
