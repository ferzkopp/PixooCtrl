"""
Lava lamp simulation for the Divoom Pixoo 16x16.

Simulates at 64x64 resolution using metaballs, then downscales to the
16x16 Pixoo display for a smooth, organic look.
"""

import math
import random
import signal
import sys
import time

from PIL import Image

from pixoo import Pixoo

# Simulation grid
SIM_W = 64
SIM_H = 64

# Pixoo display
DISPLAY_SIZE = 16

# Timing
TARGET_FPS = 30
FRAME_DELAY = 1.0 / TARGET_FPS


class Blob:
    """A metaball blob that drifts and wobbles."""

    def __init__(self, x: float, y: float, radius: float, vy: float):
        self.x = x
        self.y = y
        self.radius = radius
        self.vy = vy  # vertical drift speed
        self.vx = 0.0
        # Wobble parameters
        self.wobble_phase = random.uniform(0, 2 * math.pi)
        self.wobble_speed = random.uniform(0.5, 1.5)
        self.wobble_amp = random.uniform(0.3, 1.0)

    def update(self, dt: float):
        # Vertical drift
        self.y += self.vy * dt

        # Horizontal wobble
        self.wobble_phase += self.wobble_speed * dt
        self.vx = math.sin(self.wobble_phase) * self.wobble_amp
        self.x += self.vx * dt

        # Wrap horizontally
        if self.x < -self.radius:
            self.x = SIM_W + self.radius
        elif self.x > SIM_W + self.radius:
            self.x = -self.radius

        # Reverse direction at top/bottom (lava lamp behavior)
        if self.y < SIM_H * 0.05:
            self.vy = abs(self.vy) * random.uniform(0.8, 1.2)
        elif self.y > SIM_H * 0.95:
            self.vy = -abs(self.vy) * random.uniform(0.8, 1.2)


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    """Linearly interpolate between two RGB colors."""
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def make_blobs(count: int = 6) -> list[Blob]:
    """Spawn initial blobs spread across the lamp."""
    blobs = []
    for _ in range(count):
        x = random.uniform(SIM_W * 0.2, SIM_W * 0.8)
        y = random.uniform(SIM_H * 0.15, SIM_H * 0.85)
        radius = random.uniform(4.0, 8.0)
        vy = random.uniform(-4.0, 4.0)
        blobs.append(Blob(x, y, radius, vy))
    return blobs


def render_frame(blobs: list[Blob], t: float) -> Image.Image:
    """Render the simulation to a PIL Image at SIM_W x SIM_H."""
    # Color palette: warm lava colors
    bg_color = (15, 5, 30)        # deep purple-black
    lava_low = (180, 20, 0)       # dark red
    lava_mid = (255, 80, 0)       # orange
    lava_high = (255, 200, 50)    # bright yellow-orange

    img = Image.new("RGB", (SIM_W, SIM_H))
    pixels = img.load()

    # Slight background gradient (darker at top, warmer at bottom)
    for y in range(SIM_H):
        grad = y / SIM_H
        base = lerp_color(bg_color, (25, 8, 20), grad * 0.5)
        for x in range(SIM_W):
            pixels[x, y] = base

    # Compute metaball field
    for y in range(SIM_H):
        for x in range(SIM_W):
            field = 0.0
            for blob in blobs:
                dx = x - blob.x
                dy = y - blob.y
                dist_sq = dx * dx + dy * dy
                if dist_sq < 0.1:
                    dist_sq = 0.1
                field += (blob.radius * blob.radius) / dist_sq

            if field > 0.6:
                # Inside the lava — map intensity to color
                intensity = min(1.0, (field - 0.6) / 1.5)
                if intensity < 0.5:
                    color = lerp_color(lava_low, lava_mid, intensity * 2)
                else:
                    color = lerp_color(lava_mid, lava_high, (intensity - 0.5) * 2)
                pixels[x, y] = color
            elif field > 0.4:
                # Glow fringe
                glow_t = (field - 0.4) / 0.2
                base = pixels[x, y]
                glow = lerp_color(base, lava_low, glow_t * 0.6)
                pixels[x, y] = glow

    return img


def run(preview: bool = False):
    """Main loop: simulate and push frames to the Pixoo."""
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

    blobs = make_blobs(6)
    t = 0.0
    frame_count = 0

    print("Lava lamp running. Press Ctrl+C to stop.")

    try:
        last_time = time.monotonic()
        while running:
            frame_start = time.monotonic()

            # Update physics
            for blob in blobs:
                blob.update(FRAME_DELAY)

            # Render at simulation resolution
            frame = render_frame(blobs, t)

            # Downscale to 16x16 for display
            display_img = frame.resize(
                (DISPLAY_SIZE, DISPLAY_SIZE), Image.LANCZOS
            )

            if pixoo:
                pixoo.draw_pil_image(display_img)
            elif preview:
                # Save preview frames periodically
                if frame_count % 16 == 0:
                    display_img.save(f"lava_preview_{frame_count:04d}.png")
                    print(f"  Saved preview frame {frame_count}")

            t += FRAME_DELAY
            frame_count += 1

            # Frame rate limiter — sleep for remaining budget
            elapsed = time.monotonic() - frame_start
            remaining = FRAME_DELAY - elapsed
            if remaining > 0:
                time.sleep(remaining)

            # Report actual FPS (wall-clock, including sleep + BT send)
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
