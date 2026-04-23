"""
Plasma effect for the Divoom Pixoo 16x16.

Classic demoscene plasma using layered sine/cosine waves with a cycling
color palette.  Renders directly at 16x16 — pure math, no physics sim.
"""

import math
import signal
import sys
import time

from PIL import Image

from pixoo import Pixoo

DISPLAY_SIZE = 16
TARGET_FPS = 30
FRAME_DELAY = 1.0 / TARGET_FPS

# Color palette — 256 entries cycling through blue→magenta→orange→cyan→blue
PALETTE: list[tuple[int, int, int]] = []


def _build_palette():
    """Build a smooth 256-color cycling palette."""
    for i in range(256):
        r = int(128 + 127 * math.sin(2 * math.pi * i / 256))
        g = int(128 + 127 * math.sin(2 * math.pi * i / 256 + 2 * math.pi / 3))
        b = int(128 + 127 * math.sin(2 * math.pi * i / 256 + 4 * math.pi / 3))
        PALETTE.append((r, g, b))


_build_palette()


def render_frame(t: float) -> Image.Image:
    """Render one plasma frame at 16x16."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE))
    pixels = img.load()

    for y in range(DISPLAY_SIZE):
        for x in range(DISPLAY_SIZE):
            # Layer several sine functions for organic motion
            v = math.sin(x / 3.0 + t)
            v += math.sin(y / 2.0 + t * 0.7)
            v += math.sin((x + y) / 4.0 + t * 1.3)
            v += math.sin(math.sqrt(x * x + y * y) / 2.5 + t * 0.9)

            # Normalize to 0-255 palette index (v ranges roughly -4..+4)
            idx = int((v + 4) / 8 * 255) % 256
            pixels[x, y] = PALETTE[idx]

    return img


def run(preview: bool = False):
    """Main loop: render plasma and push frames to the Pixoo."""
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_signal)

    pixoo = None
    if not preview:
        pixoo = Pixoo.from_config()
        pixoo.connect()
        pixoo.set_brightness(60)
        print(f"Connected to Pixoo at {pixoo.mac_address}")

    t = 0.0
    frame_count = 0

    print("Plasma running. Press Ctrl+C to stop.")

    try:
        last_time = time.monotonic()
        while running:
            frame_start = time.monotonic()

            display_img = render_frame(t)

            if pixoo:
                pixoo.draw_pil_image(display_img)
            elif preview:
                if frame_count % 16 == 0:
                    display_img.save(f"plasma_preview_{frame_count:04d}.png")
                    print(f"  Saved preview frame {frame_count}")

            t += FRAME_DELAY
            frame_count += 1

            elapsed = time.monotonic() - frame_start
            remaining = FRAME_DELAY - elapsed
            if remaining > 0:
                time.sleep(remaining)

            if frame_count % 50 == 0:
                now = time.monotonic()
                actual_fps = 50.0 / (now - last_time)
                last_time = now
                print(f"  Frame {frame_count}, {actual_fps:.1f} fps")

    finally:
        if pixoo:
            pixoo.set_color(0, 0, 0)
            pixoo.disconnect()
            print("Disconnected.")


if __name__ == "__main__":
    preview_mode = "--preview" in sys.argv
    run(preview=preview_mode)
