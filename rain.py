"""
Rain & ripples effect for the Divoom Pixoo 16x16.

Top-down view of a dark water surface. Raindrops randomly splash,
creating concentric expanding ring ripples that interfere with each
other using a 2D wave-equation simulation.
"""

import random

from PIL import Image

from demo_runner import FrameContext, main as run_demo

DISPLAY_SIZE = 16
TARGET_FPS = 30

# ── Supersampling & padded simulation area ───────────────────────
# Run the wave simulation on a finer grid AND on a larger area than
# what's actually shown. We then crop the visible center for display
# and downscale. Two benefits:
#   1. Supersampling gives smooth, round ripple rings.
#   2. Padding pushes the absorbing edge band entirely OFF-screen,
#      so the visible 16×16 never sees ripples being damped — they
#      simply travel out of frame, and drops landing in the padding
#      area produce ripples that travel INTO frame.
SUPERSAMPLE = 4
SIM_PADDING = 4         # padding on each side, in display pixels
VISIBLE_SIM = DISPLAY_SIZE * SUPERSAMPLE              # 64×64
SIM_SIZE = (DISPLAY_SIZE + 2 * SIM_PADDING) * SUPERSAMPLE  # 96×96
VISIBLE_OFFSET = SIM_PADDING * SUPERSAMPLE            # 16 (sim cells)

# ── Wave simulation parameters ─────────────────────────────────────
# This is a discrete 2D wave-equation step:
#
#   next = 2·current − previous + COUPLING · (avg_neighbors − current)
#   next *= DAMPING
#
# Out-of-bounds neighbors are treated as 0 (always divide by 4),
# combined with an edge-damping mask so ripples fade out near the
# borders rather than reflecting back inward — visually this looks
# like the water surface continues past the screen edge.
DAMPING = 0.98          # energy decay per step (0..1, lower = damper)
COUPLING = 0.5          # neighbor-coupling strength
DROP_CHANCE = 0.01      # probability of a new raindrop each frame
DROP_STRENGTH = -8.0    # impulse magnitude for a raindrop splash
DROP_RADIUS = 2         # splash radius in sim cells (≈ 1/2 display pixel)
SETTLE_EPSILON = 0.01   # values with |v| below this snap to 0 (deadband)

# ── Edge fade ──────────────────────────────────────────────────────
# Cells within EDGE_FADE_BAND of the simulation border are multiplied
# by a ramp that goes from 0 at the edge to 1 at the inner boundary,
# applied every step. This acts as an absorbing boundary layer that
# lives entirely inside the off-screen padding ring — the visible
# crop never sees this damping.
EDGE_FADE_BAND = SIM_PADDING * SUPERSAMPLE  # = padding width

# ── Color mapping ──────────────────────────────────────────────────
DEEP = (5, 10, 40)            # resting / negative-displacement base
TROUGH = (2, 4, 20)           # darkest trough color
MID = (20, 60, 140)           # mid blue (positive displacement base)
HIGHLIGHT = (140, 200, 255)   # wave crest highlight
POSITIVE_NORMALIZE = 0.6      # h / this → 0..1 mix toward HIGHLIGHT
NEGATIVE_NORMALIZE = 1.0      # -h / this → 0..1 mix toward TROUGH


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    """Linearly interpolate between two RGB colors."""
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


class WaterSurface:
    """2D wave-equation simulation on a grid with absorbing edges."""

    def __init__(self, w: int, h: int):
        """Allocate the two leapfrog buffers and the precomputed edge mask."""
        self.w = w
        self.h = h
        self.current = [[0.0] * w for _ in range(h)]
        self.previous = [[0.0] * w for _ in range(h)]
        self.edge_mask = self._build_edge_mask()

    def _build_edge_mask(self) -> list:
        """Ramp from 0 at the border to 1 inside EDGE_FADE_BAND."""
        mask = [[1.0] * self.w for _ in range(self.h)]
        for y in range(self.h):
            for x in range(self.w):
                d = min(x, y, self.w - 1 - x, self.h - 1 - y)
                if d < EDGE_FADE_BAND:
                    # Smoothstep-ish ramp for a softer fade.
                    t = d / EDGE_FADE_BAND
                    mask[y][x] = t * t * (3.0 - 2.0 * t)
        return mask

    def drop(self, x: int, y: int, strength: float = DROP_STRENGTH,
             radius: int = DROP_RADIUS):
        """Inject a circular splash of ``strength`` at ``(x, y)``."""
        # Set both `current` and `previous` to the same value so the
        # leapfrog update sees zero initial velocity at the source.
        # If we only touched `current`, the next step would compute
        # 2*current - 0 and the splash cell would ring loudly at the
        # origin for many frames before radiating outward.
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                px, py = x + dx, y + dy
                if 0 <= px < self.w and 0 <= py < self.h:
                    if dx * dx + dy * dy <= radius * radius:
                        self.current[py][px] = strength
                        self.previous[py][px] = strength

    def step(self):
        """Advance the wave simulation by one timestep."""
        w, h = self.w, self.h
        cur = self.current
        prev = self.previous
        mask = self.edge_mask
        nxt = [[0.0] * w for _ in range(h)]

        for y in range(h):
            cur_row = cur[y]
            prev_row = prev[y]
            mask_row = mask[y]
            up_row = cur[y - 1] if y > 0 else None
            dn_row = cur[y + 1] if y < h - 1 else None
            nxt_row = nxt[y]
            for x in range(w):
                # Out-of-bounds neighbors treated as 0 (no reflection).
                left = cur_row[x - 1] if x > 0 else 0.0
                right = cur_row[x + 1] if x < w - 1 else 0.0
                up = up_row[x] if up_row is not None else 0.0
                dn = dn_row[x] if dn_row is not None else 0.0
                avg = (left + right + up + dn) * 0.25
                c = cur_row[x]
                val = 2.0 * c - prev_row[x] + COUPLING * (avg - c)
                val = val * DAMPING * mask_row[x]
                # Deadband: snap negligible residuals to 0 so the
                # surface actually settles instead of jittering forever.
                if -SETTLE_EPSILON < val < SETTLE_EPSILON:
                    val = 0.0
                nxt_row[x] = val

        self.previous = self.current
        self.current = nxt


def render_water(surface: WaterSurface) -> Image.Image:
    """Render the visible center crop of the surface, then downscale."""
    img = Image.new("RGB", (VISIBLE_SIM, VISIBLE_SIM))
    pixels = img.load()

    y0 = VISIBLE_OFFSET
    x0 = VISIBLE_OFFSET
    for vy in range(VISIBLE_SIM):
        row = surface.current[y0 + vy]
        for vx in range(VISIBLE_SIM):
            h = row[x0 + vx]
            if h > 0:
                t = h / POSITIVE_NORMALIZE
                if t > 1.0:
                    t = 1.0
                color = lerp_color(MID, HIGHLIGHT, t)
            elif h < 0:
                t = -h / NEGATIVE_NORMALIZE
                if t > 1.0:
                    t = 1.0
                color = lerp_color(DEEP, TROUGH, t)
            else:
                color = DEEP
            pixels[vx, vy] = color

    if VISIBLE_SIM != DISPLAY_SIZE:
        img = img.resize((DISPLAY_SIZE, DISPLAY_SIZE), Image.LANCZOS)
    return img


def make_state() -> dict:
    """Build the per-run state: a fresh padded water surface."""
    return {"surface": WaterSurface(SIM_SIZE, SIM_SIZE)}


def render(ctx: FrameContext) -> Image.Image:
    """Maybe spawn a drop, step the wave equation, and render the visible crop."""
    surface: WaterSurface = ctx.state["surface"]
    if random.random() < DROP_CHANCE:
        # Spawn anywhere; the edge-fade band will absorb splashes
        # near the border naturally.
        rx = random.randint(0, SIM_SIZE - 1)
        ry = random.randint(0, SIM_SIZE - 1)
        surface.drop(rx, ry)
    surface.step()
    return render_water(surface)


if __name__ == "__main__":
    run_demo(
        name="rain",
        description="Rain & ripples wave-equation simulation for the Pixoo 16x16.",
        target_fps=TARGET_FPS,
        render=render,
        state_factory=make_state,
    )
