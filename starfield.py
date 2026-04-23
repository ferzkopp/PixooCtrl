"""
Starfield warp effect for the Divoom Pixoo 16x16.

Classic "flying through space" animation — stars stream outward from the
center, accelerating as they approach the screen edges.
"""

import random
import signal
import sys
import time

from PIL import Image

from pixoo import Pixoo

DISPLAY_SIZE = 16
CENTER = DISPLAY_SIZE / 2.0
TARGET_FPS = 30
FRAME_DELAY = 1.0 / TARGET_FPS

NUM_STARS = 8
MAX_DEPTH = 32.0


class Star:
    """A star with 3D position projected onto the 2D display."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.x = random.uniform(-MAX_DEPTH, MAX_DEPTH)
        self.y = random.uniform(-MAX_DEPTH, MAX_DEPTH)
        self.z = random.uniform(1.0, MAX_DEPTH)
        self.prev_sx: float | None = None
        self.prev_sy: float | None = None

    def update(self, speed: float):
        self.z -= speed

        if self.z <= 0.2:
            self.reset()
            return

        sx = CENTER + self.x / self.z * CENTER
        sy = CENTER + self.y / self.z * CENTER

        if not (0 <= sx < DISPLAY_SIZE and 0 <= sy < DISPLAY_SIZE):
            self.reset()
            return

        self.prev_sx = sx
        self.prev_sy = sy

    @property
    def screen_x(self) -> float:
        return CENTER + self.x / self.z * CENTER

    @property
    def screen_y(self) -> float:
        return CENTER + self.y / self.z * CENTER

    @property
    def brightness(self) -> float:
        """Closer stars are brighter, with a small floor."""
        return max(0.15, min(1.0, 1.0 - self.z / MAX_DEPTH))


def render_frame(stars: list[Star]) -> Image.Image:
    """Render all stars onto a 16x16 black image."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), (0, 0, 0))
    pixels = img.load()

    for star in stars:
        if star.z <= 0.2:
            continue

        sx = int(star.screen_x)
        sy = int(star.screen_y)

        if not (0 <= sx < DISPLAY_SIZE and 0 <= sy < DISPLAY_SIZE):
            continue

        b = star.brightness

        # All stars are white, just scaled by brightness
        v = int(255 * b)
        color = (v, v, v)

        pixels[sx, sy] = color

        # Draw a short trail for fast (close) stars
        if b > 0.5 and star.prev_sx is not None:
            tx = int(star.prev_sx)
            ty = int(star.prev_sy)
            if 0 <= tx < DISPLAY_SIZE and 0 <= ty < DISPLAY_SIZE:
                dim = 0.3
                trail = (int(color[0] * dim), int(color[1] * dim), int(color[2] * dim))
                pixels[tx, ty] = trail

    return img


def run(preview: bool = False):
    """Main loop: simulate starfield and push frames to the Pixoo."""
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_signal)

    pixoo = None
    if not preview:
        pixoo = Pixoo.from_config()
        pixoo.connect()
        pixoo.set_brightness(80)
        print(f"Connected to Pixoo at {pixoo.mac_address}")

    stars = [Star() for _ in range(NUM_STARS)]
    # Spread initial depths so stars don't all appear at once
    for star in stars:
        star.z = random.uniform(0.5, MAX_DEPTH)

    frame_count = 0
    speed = 0.4  # z units per frame

    print("Starfield running. Press Ctrl+C to stop.")

    try:
        last_time = time.monotonic()
        while running:
            frame_start = time.monotonic()

            for star in stars:
                star.update(speed)

            display_img = render_frame(stars)

            if pixoo:
                pixoo.draw_pil_image(display_img)
            elif preview:
                if frame_count % 16 == 0:
                    display_img.save(f"starfield_preview_{frame_count:04d}.png")
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
