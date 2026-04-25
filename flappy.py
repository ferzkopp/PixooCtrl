"""
Flappy bird simulation for the Divoom Pixoo 16x16.

A small auto-piloted bird hovers at a fixed column near the left side of
the display while the level scrolls endlessly from right to left. Green
pipes spawn off the right edge with a randomised vertical gap, and the
bird flaps just enough to keep itself centred in the next opening.

The bird is a 3x3 sprite with a 2-frame wing flap, a black eye and an
orange beak that pokes one pixel to the right.
"""

import random

from PIL import Image

from demo_runner import FrameContext, main as run_demo

DISPLAY_SIZE = 16
TARGET_FPS = 20

# ── Bird ───────────────────────────────────────────────────────────
# The bird's left edge is fixed near the middle-left of the display so
# the level visibly scrolls past it.
BIRD_X = 5
BIRD_W = 3
BIRD_H = 3

GRAVITY = 0.25         # px/frame² pulling the bird down
FLAP_VY = -1.4         # vertical velocity injected by a flap
MAX_VY = 2.0           # terminal velocity clamp (both directions)
FLAP_ANIM_FRAMES = 4   # how long the wing-up / brightness pulse lasts

# ── Pipes ──────────────────────────────────────────────────────────
PIPE_WIDTH = 2
PIPE_GAP = 6                # vertical opening height in pixels
# Pipes spawn at PIPE_SPAWN_MIN..PIPE_SPAWN_MAX pixels apart so the
# rhythm of obstacles isn't perfectly regular — occasionally a wider
# stretch of sky goes by, which makes the difficulty feel less robotic.
PIPE_SPAWN_MIN = 8
PIPE_SPAWN_MAX = 10
SCROLL_PX_PER_FRAME = 0.4   # sub-pixel scroll so motion looks smooth at 20 fps

# Gap top-row may span [GAP_Y_MIN, GAP_Y_MAX] inclusive. Leaves at least
# one row of pipe both above and below the gap so the rim caps render.
GAP_Y_MIN = 1
GAP_Y_MAX = DISPLAY_SIZE - PIPE_GAP - 1   # = 9 with defaults

# ── Colors ─────────────────────────────────────────────────────────
SKY_TOP = (10, 30, 70)
SKY_BOTTOM = (50, 110, 170)
PIPE = (40, 180, 60)
PIPE_DARK = (20, 110, 35)
PIPE_LIGHT = (140, 230, 140)
BIRD_BODY = (255, 215, 0)
BIRD_BODY_FLASH = (255, 255, 200)   # near-white pulse during a flap
BIRD_WING = (230, 150, 0)
BIRD_WING_FLASH = (255, 230, 120)   # bright wing while flapping up
BIRD_BEAK = (255, 110, 0)
BIRD_EYE = (20, 20, 20)


class Pipe:
    """A vertical pipe pair with a gap. ``x`` is the left edge as a float."""

    def __init__(self, x: float, gap_y: int, spacing: int):
        self.x = x
        self.gap_y = gap_y      # top row of the opening (inclusive)
        self.spacing = spacing  # x-distance to the next spawned pipe


def make_state() -> dict:
    """Build the per-run state: bird centred, no velocity, no pipes spawned yet."""
    return {
        "bird_y": (DISPLAY_SIZE - BIRD_H) / 2.0,
        "vy": 0.0,
        "flap_anim": 0,
        "pipes": [],
    }


def _spawn_pipe(pipes: list[Pipe]) -> None:
    spacing = random.randint(PIPE_SPAWN_MIN, PIPE_SPAWN_MAX)
    pipes.append(
        Pipe(float(DISPLAY_SIZE), random.randint(GAP_Y_MIN, GAP_Y_MAX), spacing)
    )


def _next_pipe_for_bird(pipes: list[Pipe]) -> Pipe | None:
    """The nearest pipe whose right edge has not yet passed the bird."""
    candidates = [p for p in pipes if p.x + PIPE_WIDTH > BIRD_X]
    return min(candidates, key=lambda p: p.x) if candidates else None


def _update(state: dict) -> None:
    pipes: list[Pipe] = state["pipes"]

    # Spawn a new pipe once the previous one has scrolled in by its own
    # randomised spacing — this keeps the rhythm uneven without ever
    # spawning two pipes on top of each other.
    if not pipes or pipes[-1].x <= DISPLAY_SIZE - pipes[-1].spacing:
        _spawn_pipe(pipes)

    # Scroll pipes leftward and drop ones that have left the screen.
    for p in pipes:
        p.x -= SCROLL_PX_PER_FRAME
    state["pipes"] = [p for p in pipes if p.x + PIPE_WIDTH > -1]

    # ── Autopilot ─────────────────────────────────────────────────
    # Aim for the centre of the next pipe's gap, biased very slightly
    # upward so gravity has time to pull the bird down into position.
    target = state["bird_y"]
    np = _next_pipe_for_bird(state["pipes"])
    if np is not None:
        gap_centre_top = np.gap_y + (PIPE_GAP - BIRD_H) / 2.0
        target = gap_centre_top - 0.5

    bird_y = state["bird_y"]
    vy = state["vy"]

    # Flap when below the target and not already shooting upward — this
    # naturally produces the recognisable bobbing arc of a flappy bird.
    if bird_y > target and vy > -0.3:
        vy = FLAP_VY
        state["flap_anim"] = FLAP_ANIM_FRAMES

    # Physics
    vy = max(-MAX_VY, min(MAX_VY, vy + GRAVITY))
    bird_y += vy

    # Soft clamp at the top/bottom of the screen so a bad alignment does
    # not let the bird fly off the panel.
    if bird_y < 0:
        bird_y, vy = 0.0, 0.0
    elif bird_y > DISPLAY_SIZE - BIRD_H:
        bird_y, vy = float(DISPLAY_SIZE - BIRD_H), 0.0

    state["bird_y"] = bird_y
    state["vy"] = vy
    if state["flap_anim"] > 0:
        state["flap_anim"] -= 1


def _draw_sky(px) -> None:
    for y in range(DISPLAY_SIZE):
        t = y / (DISPLAY_SIZE - 1)
        r = int(SKY_TOP[0] + (SKY_BOTTOM[0] - SKY_TOP[0]) * t)
        g = int(SKY_TOP[1] + (SKY_BOTTOM[1] - SKY_TOP[1]) * t)
        b = int(SKY_TOP[2] + (SKY_BOTTOM[2] - SKY_TOP[2]) * t)
        for x in range(DISPLAY_SIZE):
            px[x, y] = (r, g, b)


def _draw_pipes(px, pipes: list[Pipe]) -> None:
    for p in pipes:
        x0 = int(round(p.x))
        gap_top = p.gap_y
        gap_bot = p.gap_y + PIPE_GAP - 1   # last row inside the gap
        for dx in range(PIPE_WIDTH):
            x = x0 + dx
            if not (0 <= x < DISPLAY_SIZE):
                continue
            for y in range(DISPLAY_SIZE):
                if gap_top <= y <= gap_bot:
                    continue
                # left highlight, right shadow, base fill in between
                if dx == 0:
                    color = PIPE_LIGHT
                elif dx == PIPE_WIDTH - 1:
                    color = PIPE_DARK
                else:
                    color = PIPE
                # Rim caps right above and below the opening
                if y == gap_top - 1 or y == gap_bot + 1:
                    color = PIPE_DARK
                px[x, y] = color


def _draw_bird(px, bird_y: float, flap_phase: float) -> None:
    """Render the bird sprite.

    `flap_phase` is 0.0 when at rest and ramps from 1.0 down to 0.0 over
    the FLAP_ANIM_FRAMES that follow a flap. While > 0 the body brightens
    toward white and the wing both moves up and flashes — at 3x3 the
    wing motion alone is hard to see, so the brightness pulse is what
    actually sells the flap on a 16x16 panel.
    """
    by = int(round(bird_y))
    bx = BIRD_X
    flapping = flap_phase > 0.0
    body_color = _lerp_color(BIRD_BODY, BIRD_BODY_FLASH, flap_phase)

    # Solid 3x3 body (brightness-pulsed during a flap)
    for dy in range(BIRD_H):
        for dx in range(BIRD_W):
            x, y = bx + dx, by + dy
            if 0 <= x < DISPLAY_SIZE and 0 <= y < DISPLAY_SIZE:
                px[x, y] = body_color

    # Wing on the left side: down by default, up + flashing while flapping.
    wing_y = by + (0 if flapping else 2)
    wing_color = _lerp_color(BIRD_WING, BIRD_WING_FLASH, flap_phase)
    if 0 <= bx < DISPLAY_SIZE and 0 <= wing_y < DISPLAY_SIZE:
        px[bx, wing_y] = wing_color

    # Black eye in the top-right of the body
    ex, ey = bx + 2, by
    if 0 <= ex < DISPLAY_SIZE and 0 <= ey < DISPLAY_SIZE:
        px[ex, ey] = BIRD_EYE

    # Orange beak poking one pixel further right, on the middle row
    beak_x, beak_y = bx + BIRD_W, by + 1
    if 0 <= beak_x < DISPLAY_SIZE and 0 <= beak_y < DISPLAY_SIZE:
        px[beak_x, beak_y] = BIRD_BEAK


def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def render(ctx: FrameContext) -> Image.Image:
    """Advance the simulation one tick and draw the resulting frame."""
    state = ctx.state
    _update(state)

    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), SKY_TOP)
    px = img.load()

    _draw_sky(px)
    _draw_pipes(px, state["pipes"])
    flap_phase = state["flap_anim"] / FLAP_ANIM_FRAMES if FLAP_ANIM_FRAMES else 0.0
    _draw_bird(px, state["bird_y"], flap_phase)

    return img


if __name__ == "__main__":
    run_demo(
        name="flappy",
        description="Endless auto-piloted flappy bird simulation for the Pixoo 16x16.",
        target_fps=TARGET_FPS,
        render=render,
        state_factory=make_state,
    )
