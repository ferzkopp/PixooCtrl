# PixooCtrl

Control a Divoom Pixoo 16x16 LED display from Windows via Bluetooth — no vendor app required.

## Overview

This project provides:

- **`setup.ps1`** — Prerequisite installer: checks Python 3.9+, creates a virtual environment, installs Pillow, verifies the Bluetooth adapter and `socket.AF_BLUETOOTH` support, and checks for already-paired Pixoo devices.
- **`find_and_pair_pixoo.ps1`** — Device discovery & pairing: scans the Windows Bluetooth registry for paired Pixoo/Divoom devices, extracts the MAC address. If not found, opens Windows Bluetooth Settings, polls for pairing, and saves the result to `pixoo_config.json`.
- **`pixoo.py`** — Python control library: pixel buffer with `set_pixel()` / `show()`, image and GIF sending, brightness, solid color, and mode control over Bluetooth Classic (RFCOMM).
- **`test_pixoo.py`** — Visual test suite: 8 tests including solid colors, brightness ramp, diagonal line, checkerboard, nested rectangles, gradient, smiley face, and clock mode.
- **`lava_lamp.py`** — Lava lamp simulation using metaballs, rendered at 64x64 and downscaled to 16x16.
- **`plasma.py`** — Classic demoscene plasma effect with layered sine/cosine waves and cycling color palette.
- **`starfield.py`** — Starfield warp effect — stars stream outward from the center with trails and glow.
- **`rain.py`** — Top-down rain & ripples on a dark water surface using 2D wave-equation simulation.
- **`snake.py`** — Endless auto-playing snake game with AI steering, growth, and a dramatic death animation.

## Requirements

- Windows 10/11
- Python 3.9 or later (for `socket.AF_BLUETOOTH` support)
- A Bluetooth adapter (built-in or USB dongle)
- A Divoom Pixoo 16x16 device

## How to Use

```powershell
# 1. Install prerequisites (Python venv, Pillow, BT adapter check)
.\setup.ps1

# 2. Discover & pair your Pixoo (saves MAC address to pixoo_config.json)
.\find_and_pair_pixoo.ps1

# 3. Run the visual tests
.\.venv\Scripts\python.exe test_pixoo.py
```

## What's Automated vs Manual

| Step | Automation |
|---|---|
| Python / venv / Pillow setup | Fully automated (`setup.ps1`) |
| Bluetooth adapter detection | Fully automated (`setup.ps1`) |
| Scanning paired devices from Windows registry | Fully automated (`find_and_pair_pixoo.ps1`) |
| MAC address extraction & config saving | Fully automated (`find_and_pair_pixoo.ps1`) |
| Bluetooth pairing | Semi-automated — the script opens `ms-settings:bluetooth` and polls every 10s until it detects the newly paired Pixoo. You click "Add device → Bluetooth → Pixoo" in the Settings window. |

> **Why isn't pairing fully automated?** Windows doesn't expose a CLI or API for Classic Bluetooth pairing. The script automates everything around it (opening Settings, polling, detecting, saving config).

## Using the Library in Your Own Code

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

`find_and_pair_pixoo.ps1` saves a `pixoo_config.json` file:

```json
{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "device_name": "Pixoo",
  "bt_port": 1
}
```

If your Pixoo uses a different RFCOMM port (some audio-capable Divoom devices use port 2), edit `bt_port` in this file.

## Scripts

### Lava Lamp (`lava_lamp.py`)

A lava lamp simulation using metaballs. Renders at 64x64 resolution and downscales to the 16x16 Pixoo display at ~4 FPS.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe lava_lamp.py

# Preview mode (saves PNGs locally, no Bluetooth needed)
.\.venv\Scripts\python.exe lava_lamp.py --preview
```

Press `Ctrl+C` to stop.

### Plasma (`plasma.py`)

Classic demoscene plasma effect using layered sine/cosine waves with a smooth cycling color palette. Pure math — no physics simulation. The entire screen flows with psychedelic gradients that shift and morph over time.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe plasma.py

# Preview mode
.\.venv\Scripts\python.exe plasma.py --preview
```

Press `Ctrl+C` to stop.

### Starfield Warp (`starfield.py`)

"Flying through space" effect — stars stream outward from the center of the screen, accelerating as they approach the edges. Close stars leave short trails and glow brighter white; distant stars are dim blue dots.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe starfield.py

# Preview mode
.\.venv\Scripts\python.exe starfield.py --preview
```

Press `Ctrl+C` to stop.

### Rain & Ripples (`rain.py`)

Top-down view of a dark water surface. Raindrops randomly splash, creating concentric expanding ring ripples that interfere with each other using a 2D wave-equation simulation. Wave crests shimmer bright blue-white; troughs go deep dark blue.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe rain.py

# Preview mode
.\.venv\Scripts\python.exe rain.py --preview
```

Press `Ctrl+C` to stop.

### Snake (`snake.py`)

Endless auto-playing snake game. A green snake with a bright head chases multi-colored food targets, growing longer with each meal. Simple AI steers toward the nearest food while avoiding self-collision and dead ends (flood-fill lookahead). When the snake eats itself a dramatic death animation plays at an increased framerate: the snake turns red, the head flickers white, and segments flash white as they disappear from tail to head. Afterwards the snake's final length is shown on screen before the game restarts.

```powershell
# Run on the Pixoo
.\.venv\Scripts\python.exe snake.py

# Preview mode
.\.venv\Scripts\python.exe snake.py --preview
```

Press `Ctrl+C` to stop.

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
