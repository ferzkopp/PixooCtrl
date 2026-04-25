# PixooCtrl

Control a Divoom Pixoo 16x16 LED display from Windows via Bluetooth — no vendor app required.

## Overview

This project provides:

**Setup**

- **`setup.ps1`** — Windows setup flow: checks Python 3.9+, creates a virtual environment, installs Pillow, verifies the Bluetooth adapter and `socket.AF_BLUETOOTH` support, scans for a paired Pixoo/Divoom device, and saves `pixoo_config.json`. Run it once before pairing and again after pairing.
- **`setup.sh`** — Linux setup flow: same as above, plus a check for BlueZ tooling (`bluetoothctl`).

**Library & tests**

- **`pixoo.py`** — Python control library: pixel buffer with `set_pixel()` / `show()`, image and GIF sending, brightness, solid color, and mode control over Bluetooth Classic (RFCOMM).
- **`test_pixoo.py`** — Visual test suite: 8 tests including solid colors, brightness ramp, diagonal line, checkerboard, nested rectangles, gradient, smiley face, and clock mode.

**Demos** (each runnable on the device or in `--preview` mode)

- **`lava_lamp.py`** — Lava lamp simulation using metaballs, rendered at 64x64 and downscaled to 16x16.
- **`plasma.py`** — Classic demoscene plasma effect with layered sine/cosine waves and cycling color palette.
- **`starfield.py`** — Starfield warp effect — stars stream outward from the center with trails and glow.
- **`rain.py`** — Top-down rain & ripples on a dark water surface using 2D wave-equation simulation.
- **`snake.py`** — Endless auto-playing snake game with AI steering, growth, and a dramatic death animation.
- **`hello_kitty.py`** — Hello Kitty face with natural-looking random eye blinks.
- **`flappy.py`** — Endless auto-piloted flappy bird simulation: a small bird hovers near the centre while pipes scroll past from right to left.

**Tooling**

- **`gen_previews.py`** — Developer tool: regenerates the simulated-Pixoo preview images shown below in `images/` by running each demo headlessly and compositing the captured 16x16 frame onto a synthetic device bezel.

## Requirements

### Windows

- Windows 10/11
- PowerShell 5.1 or PowerShell 7+
- Python 3.9 or later (for `socket.AF_BLUETOOTH` support)
- A Bluetooth adapter (built-in or USB dongle)
- A Divoom Pixoo 16x16 device

### Linux

- A Linux distribution with BlueZ Bluetooth support installed and running (`bluetoothd`, `bluetoothctl`)
- Python 3.9 or later with `socket.AF_BLUETOOTH` support
- `python3-venv` (or the equivalent package for your distro) so you can create a virtual environment
- A Bluetooth adapter (built-in or USB dongle)
- A Divoom Pixoo 16x16 device paired through your desktop Bluetooth settings or `bluetoothctl`

The PowerShell helper script in this repo is Windows-only. On Linux, use `./setup.sh`, then pair the device and re-run it so it can save `pixoo_config.json`.

## How to Use

### Windows

```powershell
# 1. Install prerequisites (Python venv, Pillow, BT adapter check)
.\setup.ps1

# 2. Pair your Pixoo in Windows Bluetooth Settings, then run setup again
.\setup.ps1

# 3. Run the visual tests
.\.venv\Scripts\python.exe test_pixoo.py
```

### Linux

```bash
# 1. Install prerequisites, create .venv, install Pillow, and check BlueZ
chmod +x ./setup.sh
./setup.sh

# 2. Pair the Pixoo in your desktop Bluetooth settings or with bluetoothctl,
#    then re-run setup.sh so it can detect the paired device and save
#    pixoo_config.json automatically
./setup.sh

# 3. Run the visual tests
./.venv/bin/python test_pixoo.py
```

If your distro ships multiple Python binaries, make sure `python` inside the virtual environment resolves to the same interpreter used to create it.

If `setup.sh` cannot identify the Pixoo automatically, create `pixoo_config.json` manually in the repo root with the device MAC address and `bt_port` set to `1`.

To verify BlueZ support on Linux manually, check these before pairing:

- `bluetoothctl --version` should succeed.
- `systemctl status bluetooth` should show the service as active on systemd-based distros.
- `bluetoothctl list` should show at least one controller.
- `bluetoothctl devices Paired` will show whether the Pixoo is already paired.

If Bluetooth access still fails on Linux, verify that BlueZ is running and that your user can access the Bluetooth stack on the host.

## What's Automated vs Manual

| Step | Automation |
|---|---|
| Python / venv / Pillow setup | Fully automated (`setup.ps1`) |
| Bluetooth adapter detection | Fully automated (`setup.ps1`) |
| Scanning paired devices from Windows registry | Fully automated (`setup.ps1`) |
| MAC address extraction & config saving | Fully automated (`setup.ps1`) |
| Bluetooth pairing | Semi-automated — `setup.ps1` opens `ms-settings:bluetooth`; you click "Add device → Bluetooth → Pixoo" in the Settings window, then run `setup.ps1` again to save config. |

> **Why isn't pairing fully automated?** Windows doesn't expose a CLI or API for Classic Bluetooth pairing. The script automates everything around it (opening Settings, detecting paired devices, and saving config after you pair).

## Using the Library in Your Own Code

To embed PixooCtrl in another project, copy these files into your project root:

- **`pixoo.py`** — the control library itself (the only runtime dependency, plus Pillow).
- **`setup.ps1`** *(Windows)* or **`setup.sh`** *(Linux)* — the helper that creates the venv, installs Pillow, and writes `pixoo_config.json` with your device's MAC address. Run it the same way as in this repo (once before pairing, once after) so `Pixoo.from_config()` can find the device.

Once those are in place, `pip install pillow` (or rerun the setup script) and import the library:

```python
from pixoo import Pixoo

# Load MAC address from pixoo_config.json
pixoo = Pixoo.from_config()
pixoo.connect()

# Set brightness (0–100)
pixoo.set_brightness(80)

# Fill display with a solid color
pixoo.set_color(255, 0, 0)  # red

# Set individual pixels and push to display
pixoo.clear()
pixoo.set_pixel(5, 5, 255, 255, 0)   # yellow at (5,5)
pixoo.set_pixel(10, 3, 0, 255, 0)    # green at (10,3)
pixoo.fill_rect(0, 0, 4, 4, 0, 0, 255)  # blue 4x4 square at top-left
pixoo.show()

# Send an image file (auto-resized to 16x16)
pixoo.draw_image("my_art.png")

# Send an animated GIF
pixoo.draw_gif("animation.gif", speed=100)

# Switch to built-in clock mode
pixoo.set_mode(Pixoo.MODE_CLOCK)

# Or construct with an explicit MAC address
pixoo = Pixoo("AA:BB:CC:DD:EE:FF", port=1)
pixoo.connect()

pixoo.disconnect()
```

## Configuration File

`setup.ps1` on Windows and `setup.sh` on Linux save a `pixoo_config.json` file:

```json
{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "device_name": "Pixoo",
  "bt_port": 1
}
```

If your Pixoo uses a different RFCOMM port (some audio-capable Divoom devices use port 2), edit `bt_port` in this file.

## Demo Scripts

### Lava Lamp (`lava_lamp.py`)

<img src="images/lava_lamp.png" alt="Lava Lamp preview" width="240">

A lava lamp simulation using metaballs. Renders at 64x64 resolution and downscales to the 16x16 Pixoo display at ~4 FPS.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe lava_lamp.py

# Preview mode (saves PNGs locally, no Bluetooth needed)
.\.venv\Scripts\python.exe lava_lamp.py --preview
```

Press `Ctrl+C` to stop.

### Plasma (`plasma.py`)

<img src="images/plasma.png" alt="Plasma preview" width="240">

Classic demoscene plasma effect using layered sine/cosine waves with a smooth cycling color palette. Pure math — no physics simulation. The entire screen flows with psychedelic gradients that shift and morph over time.

Three distinct palettes — **rainbow**, **neon** (smooth magenta/cyan pulses on a dark background), and **ocean** (blues/cyans/purples) — are cycled on a 30 second period: each palette holds for 27 seconds, then crossfades into the next over 3 seconds. Tune `HOLD_SECONDS` and `FADE_SECONDS` at the top of [plasma.py](plasma.py) to taste.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe plasma.py

# Preview mode
.\.venv\Scripts\python.exe plasma.py --preview
```

Press `Ctrl+C` to stop.

### Starfield Warp (`starfield.py`)

<img src="images/starfield.png" alt="Starfield preview" width="240">

"Flying through space" effect — stars stream outward from the center of the screen, accelerating as they approach the edges. Close stars leave short trails and glow brighter white; distant stars are dim blue dots.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe starfield.py

# Preview mode
.\.venv\Scripts\python.exe starfield.py --preview
```

Press `Ctrl+C` to stop.

### Rain & Ripples (`rain.py`)

<img src="images/rain.png" alt="Rain preview" width="240">

Top-down view of a dark water surface. Raindrops randomly splash, creating concentric expanding ring ripples that interfere with each other using a 2D wave-equation simulation. Wave crests shimmer bright blue-white; troughs go deep dark blue.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe rain.py

# Preview mode
.\.venv\Scripts\python.exe rain.py --preview
```

Press `Ctrl+C` to stop.

### Snake (`snake.py`)

<img src="images/snake.png" alt="Snake preview" width="240">

Endless auto-playing snake game. A green snake with a bright head chases multi-colored food targets, growing longer with each meal. Two different AIs take turns each game so the playstyle visibly changes between rounds:

- **Flood-fill greedy** — picks the safe neighbour that minimises Manhattan distance to the nearest food while maximising reachable area (avoids tight pockets).
- **A\* pathfinding** — computes the shortest path to the nearest food avoiding the body, falls back to chasing the tail when no path exists.

When the snake dies (collides with itself or a wall) a dramatic death animation plays at an increased framerate: the snake turns red, the head flickers white, and segments flash white as they disappear from tail to head. Afterwards a two-line score screen appears — the just-finished length on top in white, and `HS<n>` below in dim cyan showing the best length so far this session. When a run ties or beats the previous high both lines turn gold to celebrate the new record. The highscore is kept in memory only (it resets when the script restarts). Then the next game starts with the other AI.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe snake.py

# Preview mode
.\.venv\Scripts\python.exe snake.py --preview
```

Press `Ctrl+C` to stop.

### Hello Kitty (`hello_kitty.py`)

<img src="images/hello_kitty.png" alt="Hello Kitty preview" width="240">

Displays Hello Kitty's face on the Pixoo. The eyes blink at natural random intervals (2–6 seconds apart), with smooth open → half-closed → closed → half-closed → open transitions and occasional double-blinks.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe hello_kitty.py

# Preview mode
.\.venv\Scripts\python.exe hello_kitty.py --preview
```

Press `Ctrl+C` to stop.

### Flappy Bird (`flappy.py`)

<img src="images/flappy.png" alt="Flappy Bird preview" width="240">

Endless auto-piloted flappy bird simulation. A 3x3 yellow bird with a black eye, orange beak and a 2-frame wing flap stays at a fixed column near the centre while green pipes scroll past from right to left. The bird's autopilot aims for the middle of the next pipe's gap and flaps just enough to keep itself there, producing the recognisable bobbing arc.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe flappy.py

# Preview mode
.\.venv\Scripts\python.exe flappy.py --preview
```

Press `Ctrl+C` to stop.

### Regenerating the preview images (`gen_previews.py`)

The preview images embedded above live in `images/` and are produced by `gen_previews.py`. The script imports each demo's `make_state` / `render` callbacks directly (no Bluetooth, no subprocesses), drives the render function for a number of frames so the demo "warms up" to a visually interesting state, then composites the resulting 16x16 frame onto a synthetic Pixoo bezel (rounded plastic frame, dark grid cells with bright LED centres, soft glow halo, top indicator dots and bottom button).

```powershell
.\.venv\Scripts\python.exe gen_previews.py
```

Outputs are written to `images/<demo>.png`. Capture parameters (frame count, RNG seed) for each demo are listed in the `DEMOS` table at the bottom of the script — tweak them if you want a different moment captured.

## Troubleshooting

- **Can't connect:** Make sure the Pixoo is powered on, paired in Windows Bluetooth settings, and that no other app (e.g., the Divoom phone app) is currently connected to it.
- **`socket.AF_BLUETOOTH` not available:** Reinstall Python 3.9+ from [python.org](https://www.python.org/downloads/). Some bundled/store versions may not include Bluetooth socket support.
- **Wrong port:** Try editing `bt_port` to `2` in `pixoo_config.json`.
- **Connection drops immediately:** The Pixoo may need a firmware update via the Divoom app (one-time), or you may need to re-pair.

## Protocol References

- [Divoom Timebox Evo Protocol Documentation](https://github.com/RomRider/node-divoom-timebox-evo/blob/master/PROTOCOL.md)
- [virtualabs/pixoo-client](https://github.com/virtualabs/pixoo-client) — original Python Pixoo BT client
- [d03n3rfr1tz3/hass-divoom](https://github.com/d03n3rfr1tz3/hass-divoom) — most feature-complete Divoom integration
- [spezifisch/divo](https://github.com/spezifisch/divo) — Python Pixoo & Timebox Evo controller
