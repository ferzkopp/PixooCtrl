#!/usr/bin/env bash

set -u

status() { printf '[*] %s\n' "$1"; }
ok() { printf '[+] %s\n' "$1"; }
warn() { printf '[!] %s\n' "$1"; }
fail() { printf '[-] %s\n' "$1"; }

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="$project_dir/.venv"
config_path="$project_dir/pixoo_config.json"

# Verify pixoo_config.json can be written before doing anything else.
if [[ -e "$config_path" ]]; then
    if [[ ! -w "$config_path" ]]; then
        fail "$config_path exists but is not writable by the current user."
        exit 1
    fi
elif [[ ! -w "$project_dir" ]]; then
    fail "Project directory $project_dir is not writable; cannot save pixoo_config.json there."
    exit 1
fi

save_config() {
    local mac_address="$1"
    local device_name="$2"

    cat >"$config_path" <<EOF
{
  "mac_address": "$mac_address",
  "device_name": "$device_name",
  "bt_port": 1
}
EOF
    ok "Configuration saved to pixoo_config.json"
}

select_device_and_save() {
    local -n device_lines_ref=$1
    local selected_line
    local device_count="${#device_lines_ref[@]}"

    if (( device_count == 0 )); then
        return 1
    fi

    if (( device_count == 1 )); then
        selected_line="${device_lines_ref[0]}"
    else
        ok "Found $device_count candidate devices:"
        printf '\n'
        for index in "${!device_lines_ref[@]}"; do
            printf '  [%d] %s\n' "$((index + 1))" "${device_lines_ref[$index]}"
        done
        printf '\n'
        read -r -p "Select device number (1-$device_count): " selection
        if [[ ! "$selection" =~ ^[0-9]+$ ]] || (( selection < 1 || selection > device_count )); then
            fail "Invalid selection."
            return 1
        fi
        selected_line="${device_lines_ref[$((selection - 1))]}"
    fi

    if [[ "$selected_line" =~ ^Device[[:space:]]+([0-9A-F:]{17})[[:space:]]+(.+)$ ]]; then
        save_config "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
        return 0
    fi

    fail "Could not parse the selected Bluetooth device entry."
    return 1
}

status "Checking Python installation..."
python_cmd=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        version_output="$($candidate --version 2>&1)"
        if [[ "$version_output" =~ Python[[:space:]]+([0-9]+)\.([0-9]+) ]]; then
            major="${BASH_REMATCH[1]}"
            minor="${BASH_REMATCH[2]}"
            if (( major > 3 || (major == 3 && minor >= 9) )); then
                python_cmd="$candidate"
                ok "Found $version_output (>= 3.9 required for socket.AF_BLUETOOTH)"
                break
            fi
            warn "$version_output found but Python >= 3.9 is required"
        fi
    fi
done

if [[ -z "$python_cmd" ]]; then
    fail "Python >= 3.9 not found. Install Python and python3-venv from your distro packages."
    exit 1
fi

if [[ ! -d "$venv_dir" ]]; then
    status "Creating virtual environment in .venv ..."
    if ! "$python_cmd" -m venv "$venv_dir"; then
        fail "Failed to create virtual environment. Install your distro's venv package, such as python3-venv."
        exit 1
    fi
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

venv_python="$venv_dir/bin/python"

if [[ ! -x "$venv_python" ]]; then
    fail "venv python not found at $venv_python"
    exit 1
fi

status "Installing required Python packages..."
if ! "$venv_python" -m pip install --upgrade pip >/dev/null; then
    fail "Failed to upgrade pip inside the virtual environment"
    exit 1
fi
if ! "$venv_python" -m pip install Pillow >/dev/null; then
    fail "Failed to install Pillow"
    exit 1
fi
ok "Pillow installed"

status "Verifying Bluetooth socket support in Python..."
if "$venv_python" - <<'PY' >/dev/null 2>&1
import socket
required = ("AF_BLUETOOTH", "BTPROTO_RFCOMM")
missing = [name for name in required if not hasattr(socket, name)]
raise SystemExit(1 if missing else 0)
PY
then
    ok "Python exposes AF_BLUETOOTH and BTPROTO_RFCOMM"
else
    warn "This Python build is missing Bluetooth socket support. RFCOMM connections may not work on this host."
fi

status "Checking BlueZ userspace tools..."
if command -v bluetoothctl >/dev/null 2>&1; then
    ok "Found bluetoothctl"
else
    warn "bluetoothctl not found. Install BlueZ tools for your distro."
fi

status "Checking Bluetooth service..."
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet bluetooth; then
        ok "bluetooth service is running"
    else
        warn "bluetooth service is not running. Start it with: sudo systemctl enable --now bluetooth"
    fi
else
    warn "systemctl not available. Verify your Bluetooth service manually."
fi

status "Checking for a Bluetooth adapter..."
if command -v bluetoothctl >/dev/null 2>&1; then
    adapter_info="$(bluetoothctl list 2>/dev/null)"
    if [[ -n "$adapter_info" ]]; then
        ok "Bluetooth adapter found"
    else
        warn "No Bluetooth adapter reported by bluetoothctl. Check that your adapter is plugged in and not blocked."
    fi
elif command -v hciconfig >/dev/null 2>&1; then
    adapter_info="$(hciconfig 2>/dev/null | grep '^hci' || true)"
    if [[ -n "$adapter_info" ]]; then
        ok "Bluetooth adapter found"
    else
        warn "No Bluetooth adapter reported by hciconfig."
    fi
else
    warn "No adapter inspection tool found. Install BlueZ tools to verify adapter status."
fi

status "Checking for already paired Divoom/Pixoo devices..."
if command -v bluetoothctl >/dev/null 2>&1; then
    # Capture stdout and stderr separately so we can surface BlueZ errors
    # (e.g. "org.bluez.Error.NotReady") instead of silently treating them
    # as "no devices paired".
    paired_stderr_file="$(mktemp)"
    paired_output="$(bluetoothctl devices Paired 2>"$paired_stderr_file")"
    paired_status=$?
    paired_stderr="$(cat "$paired_stderr_file")"
    rm -f "$paired_stderr_file"

    if (( paired_status != 0 )) || [[ -n "$paired_stderr" ]]; then
        warn "bluetoothctl reported a problem listing paired devices:"
        if [[ -n "$paired_stderr" ]]; then
            printf '    %s\n' "$paired_stderr"
        fi
        warn "Is the Bluetooth service running and is your user allowed to use it?"
    fi

    mapfile -t all_paired_devices < <(printf '%s\n' "$paired_output" | sed '/^$/d')
    mapfile -t pixoo_devices < <(printf '%s\n' "$paired_output" | grep -iE 'pixoo|divoom' || true)

    if (( ${#pixoo_devices[@]} > 1 )); then
        warn "Multiple paired devices match 'Pixoo' or 'Divoom'. Pick the one you intend to control — picking the wrong MAC will fail silently when connecting."
    fi

    if (( ${#pixoo_devices[@]} > 0 )); then
        ok "Found paired Divoom/Pixoo device(s)."
        if select_device_and_save pixoo_devices; then
            ok "Setup complete. You can now run ./.venv/bin/python test_pixoo.py"
            exit 0
        fi
    elif (( ${#all_paired_devices[@]} > 0 )); then
        warn "No paired device matched 'Pixoo' or 'Divoom'."
        read -r -p "Is your Pixoo listed under a different Bluetooth name? (y/n): " manual_choice
        if [[ "$manual_choice" =~ ^[Yy]$ ]]; then
            if select_device_and_save all_paired_devices; then
                ok "Setup complete. You can now run ./.venv/bin/python test_pixoo.py"
                exit 0
            fi
        fi
    else
        warn "No paired Pixoo/Divoom device found yet. Pair it in your desktop Bluetooth settings or with bluetoothctl."
    fi
else
    warn "Skipping paired-device check because bluetoothctl is not available."
fi

printf '\n'
ok "Setup complete. Next steps:"
printf '  1. Pair your Pixoo in Bluetooth settings or with bluetoothctl\n'
printf '  2. Re-run ./setup.sh after pairing so it can save pixoo_config.json, or create the file manually\n'
printf '  3. Run ./.venv/bin/python test_pixoo.py to test the connection\n'