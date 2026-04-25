r"""
Generate README preview images for every PixooCtrl demo.

For each demo this script:

  1. Imports the demo module (lava_lamp, plasma, starfield, rain, snake,
     hello_kitty, flappy) and reuses its `make_state` / `render` callbacks
     directly — no subprocess, no Bluetooth.
  2. Drives the render function for a number of frames so the demo has time
     to "warm up" (e.g. snake grows, rain ripples develop, starfield fills
     with stars), then captures a representative 16x16 frame.
  3. Composites the captured frame onto a synthetic Pixoo device bezel that
     mimics the real hardware (rounded plastic frame, LED grid with bright
     centres on dark cells, a small button, three top indicators).
  4. Writes the final PNG to images/<name>.png.

Run from the repo root:

    .\.venv\Scripts\python.exe gen_previews.py
"""

from __future__ import annotations

import importlib
import random
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter

from demo_runner import FrameContext


# Output bezel geometry (pixels).
BEZEL_SIZE = 480
BEZEL_RADIUS = 36
BEZEL_COLOR = (38, 38, 40)
BEZEL_HIGHLIGHT = (62, 62, 66)
INNER_MARGIN = 36           # gap between bezel edge and LED grid
CELL_SIZE = (BEZEL_SIZE - 2 * INNER_MARGIN) // 16   # 25 px
LED_PAD = 4                 # gap between LED bright square and cell edge
CELL_BG = (14, 14, 18)


def make_bezel() -> Image.Image:
    """Build the Pixoo-shaped frame (no LEDs lit yet)."""
    img = Image.new("RGB", (BEZEL_SIZE, BEZEL_SIZE), (0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded outer frame
    d.rounded_rectangle(
        (0, 0, BEZEL_SIZE - 1, BEZEL_SIZE - 1),
        radius=BEZEL_RADIUS,
        fill=BEZEL_COLOR,
    )

    # Subtle inner highlight bevel
    d.rounded_rectangle(
        (4, 4, BEZEL_SIZE - 5, BEZEL_SIZE - 5),
        radius=BEZEL_RADIUS - 4,
        outline=BEZEL_HIGHLIGHT,
        width=1,
    )

    # Inner LED panel area (very dark, slight inset)
    grid = INNER_MARGIN
    grid_size = CELL_SIZE * 16
    d.rectangle(
        (grid - 6, grid - 6, grid + grid_size + 5, grid + grid_size + 5),
        fill=(8, 8, 10),
    )

    # Three small indicator dots near the top centre
    cx = BEZEL_SIZE // 2
    for i, dx in enumerate((-10, 0, 10)):
        d.ellipse((cx + dx - 2, 14, cx + dx + 2, 18), fill=(110, 60, 70))

    # Bottom centre button
    by = BEZEL_SIZE - 22
    d.ellipse((cx - 8, by - 8, cx + 8, by + 8), fill=(20, 20, 22))
    d.ellipse((cx - 6, by - 6, cx + 6, by + 6), fill=(50, 50, 54))

    return img


def render_panel(frame16: Image.Image) -> Image.Image:
    """Composite a 16x16 frame onto a fresh Pixoo bezel."""
    if frame16.size != (16, 16):
        frame16 = frame16.resize((16, 16), Image.LANCZOS)
    pixels = frame16.convert("RGB").load()

    bezel = make_bezel()
    glow = Image.new("RGB", bezel.size, (0, 0, 0))
    glow_d = ImageDraw.Draw(glow)
    base_d = ImageDraw.Draw(bezel)

    led_size = CELL_SIZE - 2 * LED_PAD

    for gy in range(16):
        for gx in range(16):
            r, g, b = pixels[gx, gy]
            cell_x = INNER_MARGIN + gx * CELL_SIZE
            cell_y = INNER_MARGIN + gy * CELL_SIZE
            # Cell background (always dark).
            base_d.rectangle(
                (cell_x, cell_y, cell_x + CELL_SIZE - 1, cell_y + CELL_SIZE - 1),
                fill=CELL_BG,
            )
            # Lit LED (rounded square).
            led_x = cell_x + LED_PAD
            led_y = cell_y + LED_PAD
            base_d.rounded_rectangle(
                (led_x, led_y, led_x + led_size - 1, led_y + led_size - 1),
                radius=3,
                fill=(r, g, b),
            )
            # Glow contribution (only for non-dark LEDs).
            if r + g + b > 30:
                glow_d.rounded_rectangle(
                    (led_x - 2, led_y - 2,
                     led_x + led_size + 1, led_y + led_size + 1),
                    radius=5,
                    fill=(r, g, b),
                )

    glow = glow.filter(ImageFilter.GaussianBlur(radius=6))
    # Screen-blend the glow on top of the bezel for a soft halo around lit cells.
    out = Image.new("RGB", bezel.size)
    bp = bezel.load()
    gp = glow.load()
    op = out.load()
    for y in range(bezel.size[1]):
        for x in range(bezel.size[0]):
            br, bg_, bb = bp[x, y]
            gr, gg, gb = gp[x, y]
            op[x, y] = (
                255 - ((255 - br) * (255 - gr) // 255),
                255 - ((255 - bg_) * (255 - gg) // 255),
                255 - ((255 - bb) * (255 - gb) // 255),
            )

    # Apply a rounded-rectangle alpha mask so the corners outside the bezel
    # are transparent in the final PNG (otherwise they render as black on
    # dark-themed Markdown previews).
    mask = Image.new("L", bezel.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, BEZEL_SIZE - 1, BEZEL_SIZE - 1),
        radius=BEZEL_RADIUS,
        fill=255,
    )
    out_rgba = out.convert("RGBA")
    out_rgba.putalpha(mask)
    return out_rgba


def capture_frame(
    module_name: str,
    target_fps: float,
    warmup_frames: int,
    seed: int = 12345,
) -> Image.Image:
    """Drive a demo's render() for `warmup_frames` frames, return the last frame.

    A fixed random seed keeps results reproducible across runs.
    """
    random.seed(seed)
    mod = importlib.import_module(module_name)
    make_state: Callable[[], object] | None = getattr(mod, "make_state", None)
    render = getattr(mod, "render")

    state = make_state() if make_state else None
    dt = 1.0 / target_fps
    img = None
    for f in range(warmup_frames):
        ctx = FrameContext(frame=f, t=f * dt, dt=dt, state=state)
        result = render(ctx)
        if result is not None:
            img = result
    if img is None:
        raise RuntimeError(f"{module_name} produced no frames")
    return img


def capture_snake_frame(target_length: int = 14, max_frames: int = 8000,
                        seeds: tuple[int, ...] = (11, 3, 7, 19, 23, 31, 47, 71)
                        ) -> Image.Image:
    """Run the snake demo until the live snake reaches `target_length`.

    snake.render() gates phase transitions on `time.monotonic()` rather than
    ctx.t (so it can run in real time on the device). For preview generation
    we want to advance the game as fast as possible, so we monkeypatch
    `snake.time.monotonic` to a virtual clock that advances by one frame's
    worth of seconds per render call.
    """
    snake = importlib.import_module("snake")

    virtual_now = [0.0]

    def fake_monotonic() -> float:
        return virtual_now[0]

    real_monotonic = snake.time.monotonic
    snake.time.monotonic = fake_monotonic  # type: ignore[assignment]
    try:
        best_img: Image.Image | None = None
        best_len = 0
        dt = 1.0 / 30
        for seed in seeds:
            random.seed(seed)
            virtual_now[0] = 0.0
            state = snake.make_state()
            for f in range(max_frames):
                virtual_now[0] = f * dt
                ctx = FrameContext(frame=f, t=f * dt, dt=dt, state=state)
                result = snake.render(ctx)
                if (state.phase == snake.SnakeState.PHASE_ALIVE
                        and result is not None):
                    length = len(state.game.body)
                    if length >= target_length:
                        return result
                    if length > best_len:
                        best_len = length
                        best_img = result
        if best_img is None:
            raise RuntimeError("snake produced no live frames")
        print(f"  (snake max length reached: {best_len})")
        return best_img
    finally:
        snake.time.monotonic = real_monotonic  # type: ignore[assignment]


# Per-demo capture parameters: how many frames to drive before grabbing the
# representative shot. Picked to land on visually interesting moments
# (stars trailing, snake grown, ripples interacting, pipe in frame, etc.).
DEMOS = [
    # (module_name,    target_fps, warmup_frames, seed)
    # plasma: capture ~t=35s so the preview lands in the "fire" palette
    # (showcases the palette cycling rather than the original rainbow).
    ("plasma",         30,         1050,          1),
    ("starfield",      30,         222,           11),
    ("lava_lamp",      30,         170,           7),
    ("rain",           30,         51,            9),
    ("snake",          30,         3000,          11),
    ("hello_kitty",    10,         1,             0),
    ("flappy",         20,         110,           9),
]


def main() -> None:
    """Render every demo's preview PNG into ``images/``."""
    out_dir = Path("images")
    out_dir.mkdir(exist_ok=True)

    for name, fps, warmup, seed in DEMOS:
        print(f"  Rendering preview for {name} ...")
        if name == "snake":
            frame = capture_snake_frame()
        else:
            frame = capture_frame(name, fps, warmup, seed=seed)
        panel = render_panel(frame)
        out_path = out_dir / f"{name}.png"
        panel.save(out_path)
        print(f"    -> {out_path}")


if __name__ == "__main__":
    main()
