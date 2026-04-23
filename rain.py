"""
Rain & ripples effect for the Divoom Pixoo 16x16.

Top-down view of a dark water surface.  Raindrops randomly splash,
creating concentric expanding ring ripples that interfere with each
other using a 2D wave-equation simulation.
"""

import random
import signal
import sys
import time

from PIL import Image

from pixoo import Pixoo

DISPLAY_SIZE = 16
TARGET_FPS = 30
FRAME_DELAY = 1.0 / TARGET_FPS

DAMPING = 0.8           # wave energy decay per step
DROP_CHANCE = 0.02      # probability of a new raindrop each frame
DROP_STRENGTH = -8.0    # impulse magnitude for a raindrop splash


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    """Linearly interpolate between two RGB colors."""
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


class WaterSurface:
    """2D wave-equation simulation on a grid."""

    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        # Two buffers for the wave equation (current and previous)
        self.current = [[0.0] * w for _ in range(h)]
        self.previous = [[0.0] * w for _ in range(h)]

    def drop(self, x: int, y: int, strength: float = DROP_STRENGTH):
        """Spawn a raindrop impulse at (x, y)."""
        if 0 <= x < self.w and 0 <= y < self.h:
            self.current[y][x] = strength

    def step(self):
        """Advance the wave equation by one time step."""
        w, h = self.w, self.h
        nxt = [[0.0] * w for _ in range(h)]

        for y in range(h):
            for x in range(w):
                # Average of 4 neighbors (clamped at edges)
                neighbors = 0.0
                count = 0
                if x > 0:
                    neighbors += self.current[y][x - 1]; count += 1
                if x < w - 1:
                    neighbors += self.current[y][x + 1]; count += 1
                if y > 0:
                    neighbors += self.current[y - 1][x]; count += 1
                if y < h - 1:
                    neighbors += self.current[y + 1][x]; count += 1

                avg = neighbors / count if count else 0.0
                val = 2.0 * self.current[y][x] - self.previous[y][x] + 0.5 * (avg - self.current[y][x])
                nxt[y][x] = val * DAMPING

        self.previous = self.current
        self.current = nxt


def render_frame(surface: WaterSurface) -> Image.Image:
    """Map water height values to colors."""
    # Base water color palette
    deep = (5, 10, 40)        # deep dark blue
    mid = (20, 60, 140)       # mid blue (positive displacement)
    highlight = (140, 200, 255)  # bright highlight (wave crest)

    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE))
    pixels = img.load()

    for y in range(DISPLAY_SIZE):
        for x in range(DISPLAY_SIZE):
            h = surface.current[y][x]

            if h > 0:
                # Positive displacement — brighter
                t = min(1.0, h / 4.0)
                color = lerp_color(mid, highlight, t)
            elif h < 0:
                # Negative displacement — darker
                t = min(1.0, -h / 6.0)
                color = lerp_color(deep, (2, 4, 20), t)
            else:
                color = deep

            pixels[x, y] = color

    return img


def run(preview: bool = False):
    """Main loop: simulate water and push frames to the Pixoo."""
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

    surface = WaterSurface(DISPLAY_SIZE, DISPLAY_SIZE)
    frame_count = 0

    print("Rain & ripples running. Press Ctrl+C to stop.")

    try:
        last_time = time.monotonic()
        while running:
            frame_start = time.monotonic()

            # Randomly spawn raindrops
            if random.random() < DROP_CHANCE:
                rx = random.randint(1, DISPLAY_SIZE - 2)
                ry = random.randint(1, DISPLAY_SIZE - 2)
                surface.drop(rx, ry)

            surface.step()

            display_img = render_frame(surface)

            if pixoo:
                pixoo.draw_pil_image(display_img)
            elif preview:
                if frame_count % 16 == 0:
                    display_img.save(f"rain_preview_{frame_count:04d}.png")
                    print(f"  Saved preview frame {frame_count}")

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
