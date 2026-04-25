"""
Plasma effect for the Divoom Pixoo 16x16.

Classic demoscene plasma using layered sine/cosine waves with a cycling
color palette. Renders directly at 16x16 — pure math, no physics sim.
"""

import math

from PIL import Image

from demo_runner import FrameContext, main as run_demo

DISPLAY_SIZE = 16
TARGET_FPS = 30

# ── Layered-sine parameters ────────────────────────────────────────
# Each layer mixes a different spatial frequency and time multiplier; the
# sum of the four sines produces the "organic" look. Tweak these to taste —
# they were chosen empirically.
LAYER_X_DIV = 3.0       # horizontal stripes
LAYER_Y_DIV = 2.0       # vertical stripes
LAYER_DIAG_DIV = 4.0    # diagonal stripes (x+y)
LAYER_RADIAL_DIV = 2.5  # radial pulse (sqrt(x²+y²))
LAYER_T_MULTS = (1.0, 0.7, 1.3, 0.9)  # per-layer time multipliers
# Sum-of-4-sines ranges in [-4, +4]; map that linearly to [0, 256).
LAYER_SUM_HALF_RANGE = 4.0

PALETTE_SIZE = 256

# ── Palette cycling ────────────────────────────────────────────────
# Hold each palette for HOLD_SECONDS, then crossfade to the next over
# FADE_SECONDS. Total period per palette = HOLD + FADE.
HOLD_SECONDS = 27.0
FADE_SECONDS = 3.0
PALETTE_PERIOD = HOLD_SECONDS + FADE_SECONDS  # 30s cycle


def _build_sine_palette(
    phases: tuple[float, float, float],
    amps: tuple[float, float, float] = (127.0, 127.0, 127.0),
    offsets: tuple[float, float, float] = (128.0, 128.0, 128.0),
) -> list[tuple[int, int, int]]:
    """Build a 256-color palette from per-channel sine waves."""
    palette = []
    for i in range(PALETTE_SIZE):
        a = 2 * math.pi * i / PALETTE_SIZE
        r = int(max(0, min(255, offsets[0] + amps[0] * math.sin(a + phases[0]))))
        g = int(max(0, min(255, offsets[1] + amps[1] * math.sin(a + phases[1]))))
        b = int(max(0, min(255, offsets[2] + amps[2] * math.sin(a + phases[2]))))
        palette.append((r, g, b))
    return palette


def _build_neon_palette(
    color_a: tuple[int, int, int],
    color_b: tuple[int, int, int],
    cycles: int = 2,
    black_floor: float = 0.12,
) -> list[tuple[int, int, int]]:
    """Smoothly alternating pulses of color_a and color_b separated by darker
    bands. `cycles` controls how many A→B pairs span the palette (lower =
    smoother, broader bands). `black_floor` is the minimum brightness in the
    valleys (0 = pure black, ~0.15 keeps a soft glow so transitions don't snap).
    """
    palette = []
    for i in range(PALETTE_SIZE):
        s = (i / PALETTE_SIZE) * cycles
        frac = s - math.floor(s)
        # Smooth sine bump for the brightness envelope (one full lobe per half).
        if frac < 0.5:
            env = math.sin(math.pi * (frac / 0.5))
            color = color_a
        else:
            env = math.sin(math.pi * ((frac - 0.5) / 0.5))
            color = color_b
        env = black_floor + (1.0 - black_floor) * env
        palette.append((
            int(color[0] * env),
            int(color[1] * env),
            int(color[2] * env),
        ))
    return palette


def _build_palettes() -> list[list[tuple[int, int, int]]]:
    """Build the set of palettes the plasma will cycle through."""
    # Classic rainbow: R/G/B sines 120° apart.
    rainbow = _build_sine_palette(
        phases=(0.0, 2 * math.pi / 3, 4 * math.pi / 3),
    )
    # Neon: smooth magenta/cyan pulses on a soft dark background.
    neon = _build_neon_palette(
        color_a=(255, 40, 200),   # hot magenta
        color_b=(40, 230, 255),   # electric cyan
        cycles=2,
    )
    # Ocean: blue/cyan/purple — blue dominant, green mid, red low and shifted.
    ocean = _build_sine_palette(
        phases=(math.pi, 0.0, math.pi / 2),
        amps=(80.0, 100.0, 127.0),
        offsets=(80.0, 110.0, 128.0),
    )
    return [rainbow, neon, ocean]


def _blend_palettes(
    a: list[tuple[int, int, int]],
    b: list[tuple[int, int, int]],
    f: float,
) -> list[tuple[int, int, int]]:
    """Linear crossfade between two same-length palettes; f in [0, 1]."""
    inv = 1.0 - f
    return [
        (
            int(a[i][0] * inv + b[i][0] * f),
            int(a[i][1] * inv + b[i][1] * f),
            int(a[i][2] * inv + b[i][2] * f),
        )
        for i in range(PALETTE_SIZE)
    ]


def _current_palette(
    t: float, palettes: list[list[tuple[int, int, int]]]
) -> list[tuple[int, int, int]]:
    """Pick (or crossfade) the active palette for time t."""
    n = len(palettes)
    phase = (t % (PALETTE_PERIOD * n)) / PALETTE_PERIOD
    idx = int(phase)
    local = (phase - idx) * PALETTE_PERIOD  # seconds into this palette's slot
    if local < HOLD_SECONDS:
        return palettes[idx]
    f = (local - HOLD_SECONDS) / FADE_SECONDS
    return _blend_palettes(palettes[idx], palettes[(idx + 1) % n], f)


def render_plasma(t: float, palette: list[tuple[int, int, int]]) -> Image.Image:
    """Render one plasma frame at 16x16."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE))
    pixels = img.load()
    tm = LAYER_T_MULTS

    for y in range(DISPLAY_SIZE):
        for x in range(DISPLAY_SIZE):
            v = math.sin(x / LAYER_X_DIV + t * tm[0])
            v += math.sin(y / LAYER_Y_DIV + t * tm[1])
            v += math.sin((x + y) / LAYER_DIAG_DIV + t * tm[2])
            v += math.sin(math.sqrt(x * x + y * y) / LAYER_RADIAL_DIV + t * tm[3])

            # Clamp before scaling so a future extra layer can't blow the index.
            v = max(-LAYER_SUM_HALF_RANGE, min(LAYER_SUM_HALF_RANGE, v))
            idx = int((v + LAYER_SUM_HALF_RANGE)
                      / (2 * LAYER_SUM_HALF_RANGE)
                      * (PALETTE_SIZE - 1))
            pixels[x, y] = palette[idx]

    return img


def make_state() -> dict:
    """Build the per-run state. Palettes are built here (not at import) to keep
    module load cheap."""
    return {"palettes": _build_palettes()}


def render(ctx: FrameContext) -> Image.Image:
    """Render one plasma frame using the palette active at ``ctx.t``."""
    palette = _current_palette(ctx.t, ctx.state["palettes"])
    return render_plasma(ctx.t, palette)


if __name__ == "__main__":
    run_demo(
        name="plasma",
        description="Classic demoscene plasma effect for the Pixoo 16x16.",
        target_fps=TARGET_FPS,
        render=render,
        state_factory=make_state,
    )
