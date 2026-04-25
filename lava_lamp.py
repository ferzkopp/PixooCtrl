"""
Lava lamp simulation for the Divoom Pixoo 16x16.

Simulates at 64x64 resolution using metaballs, then downscales to the
16x16 Pixoo display for a smooth, organic look.
"""

import math
import random

from PIL import Image

from demo_runner import FrameContext, main as run_demo

# ── Resolution ─────────────────────────────────────────────────────
SIM_W = 64
SIM_H = 64
DISPLAY_SIZE = 16

# ── Timing ─────────────────────────────────────────────────────────
TARGET_FPS = 30

# ── Blob physics ───────────────────────────────────────────────────
# Fewer, larger blobs read as more distinctly "blobby" once downscaled to
# 16x16 — they stay as discrete rounded shapes that occasionally merge,
# rather than blurring into one big lava puddle.
NUM_BLOBS = 4
BLOB_RADIUS_RANGE = (5.5, 9.5)        # px in simulation grid
BLOB_VY_RANGE = (-4.0, 4.0)           # vertical drift, sim-px per second
WOBBLE_SPEED_RANGE = (0.5, 1.5)       # rad/sec for horizontal wobble
WOBBLE_AMP_RANGE = (0.3, 1.0)         # sim-px amplitude
BOUNCE_SPEED_JITTER = (0.8, 1.2)      # multiplier when reversing at top/bottom
TOP_BOUNCE_FRAC = 0.05                # bounce when y < SIM_H * this
BOTTOM_BOUNCE_FRAC = 0.95             # bounce when y > SIM_H * this

# ── Field thresholds ───────────────────────────────────────────────
# A pixel's "metaball field" is sum of (radius² / distance²) over all blobs.
# Above LAVA_THRESHOLD it's solid lava; between GLOW_THRESHOLD and
# LAVA_THRESHOLD it's the soft glow fringe; below that it's background.
# Higher thresholds = tighter, more discrete blob silhouettes.
GLOW_THRESHOLD = 0.7
LAVA_THRESHOLD = 1.0
LAVA_INTENSITY_DIVISOR = 1.5          # scales (field - LAVA_THRESHOLD) → 0..1
GLOW_BLEND = 0.6                      # glow blend strength toward lava_low

# ── Colors ─────────────────────────────────────────────────────────
BG_COLOR = (15, 5, 30)            # deep purple-black
BG_GRADIENT_END = (25, 8, 20)     # bottom of the background gradient
LAVA_LOW = (180, 20, 0)           # dark red
LAVA_MID = (255, 80, 0)           # orange
LAVA_HIGH = (255, 200, 50)        # bright yellow-orange


class Blob:
    """A metaball blob that drifts and wobbles."""

    def __init__(self, x: float, y: float, radius: float, vy: float):
        self.x = x
        self.y = y
        self.radius = radius
        self.vy = vy
        self.vx = 0.0
        self.wobble_phase = random.uniform(0, 2 * math.pi)
        self.wobble_speed = random.uniform(*WOBBLE_SPEED_RANGE)
        self.wobble_amp = random.uniform(*WOBBLE_AMP_RANGE)

    def update(self, dt: float):
        """Advance the blob by ``dt`` seconds, applying drift, wobble and bounce."""
        self.y += self.vy * dt

        self.wobble_phase += self.wobble_speed * dt
        self.vx = math.sin(self.wobble_phase) * self.wobble_amp
        self.x += self.vx * dt

        # Wrap horizontally
        if self.x < -self.radius:
            self.x = SIM_W + self.radius
        elif self.x > SIM_W + self.radius:
            self.x = -self.radius

        # Reverse direction at top/bottom (lava lamp behavior)
        if self.y < SIM_H * TOP_BOUNCE_FRAC:
            self.vy = abs(self.vy) * random.uniform(*BOUNCE_SPEED_JITTER)
        elif self.y > SIM_H * BOTTOM_BOUNCE_FRAC:
            self.vy = -abs(self.vy) * random.uniform(*BOUNCE_SPEED_JITTER)


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    """Linearly interpolate between two RGB colors."""
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def make_blobs(count: int = NUM_BLOBS) -> list[Blob]:
    """Spawn initial blobs spread across the lamp."""
    blobs = []
    for _ in range(count):
        x = random.uniform(SIM_W * 0.2, SIM_W * 0.8)
        y = random.uniform(SIM_H * 0.15, SIM_H * 0.85)
        radius = random.uniform(*BLOB_RADIUS_RANGE)
        vy = random.uniform(*BLOB_VY_RANGE)
        blobs.append(Blob(x, y, radius, vy))
    return blobs


def render_sim(blobs: list[Blob]) -> Image.Image:
    """Render the simulation to a PIL Image at SIM_W x SIM_H."""
    img = Image.new("RGB", (SIM_W, SIM_H))
    pixels = img.load()

    # Slight background gradient (darker at top, warmer at bottom)
    for y in range(SIM_H):
        grad = y / SIM_H
        base = lerp_color(BG_COLOR, BG_GRADIENT_END, grad * 0.5)
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

            if field > LAVA_THRESHOLD:
                intensity = min(
                    1.0, (field - LAVA_THRESHOLD) / LAVA_INTENSITY_DIVISOR
                )
                if intensity < 0.5:
                    color = lerp_color(LAVA_LOW, LAVA_MID, intensity * 2)
                else:
                    color = lerp_color(LAVA_MID, LAVA_HIGH, (intensity - 0.5) * 2)
                pixels[x, y] = color
            elif field > GLOW_THRESHOLD:
                glow_t = (field - GLOW_THRESHOLD) / (LAVA_THRESHOLD - GLOW_THRESHOLD)
                base = pixels[x, y]
                pixels[x, y] = lerp_color(base, LAVA_LOW, glow_t * GLOW_BLEND)

    return img


def make_state() -> dict:
    """Build the per-run state: a fresh set of blobs."""
    return {"blobs": make_blobs()}


def render(ctx: FrameContext) -> Image.Image:
    """Advance every blob, render the metaball field, downscale to 16×16."""
    blobs: list[Blob] = ctx.state["blobs"]
    for blob in blobs:
        blob.update(ctx.dt)
    sim_frame = render_sim(blobs)
    return sim_frame.resize((DISPLAY_SIZE, DISPLAY_SIZE), Image.LANCZOS)


if __name__ == "__main__":
    run_demo(
        name="lava",
        description="Lava lamp metaball simulation for the Pixoo 16x16.",
        target_fps=TARGET_FPS,
        render=render,
        state_factory=make_state,
    )
