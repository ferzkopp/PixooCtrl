"""
Hello Kitty face for the Divoom Pixoo 16x16.

Renders the face directly at the panel's native 16×16 resolution as a
small set of explicit pixel layers (head → bow → eyes → nose → whiskers →
sparkle), keeping every visible pixel under explicit control rather than
relying on downscaling.

The eyes blink at random intervals with smooth open → half → closed →
half → open transitions and an occasional double-blink.
"""

import random

from PIL import Image

from demo_runner import FrameContext, main as run_demo

DISPLAY_SIZE = 16
TARGET_FPS = 10

# ── Blink timing (seconds) ─────────────────────────────────────────
BLINK_MIN_INTERVAL = 2.0       # shortest gap between blinks
BLINK_MAX_INTERVAL = 6.0       # longest gap between blinks
BLINK_CLOSE_DURATION = 0.08    # eyes fully shut
BLINK_HALF_DURATION = 0.06     # eyes half-closed (transition frame)
DOUBLE_BLINK_CHANCE = 0.15
DOUBLE_BLINK_GAP = 0.25

# ── Colors ─────────────────────────────────────────────────────────
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
NOSE = (244, 204, 70)
WHISKER = (55, 55, 55)
BOW_RED = (232, 43, 74)
BOW_HIGHLIGHT = (255, 118, 142)
SPARKLE = (255, 248, 210)
BG = (28, 16, 36)

# ── Pixel-art layers (all coordinates are 16×16) ───────────────────


def _build_head_pixels() -> set[tuple[int, int]]:
    """Round face shape, centered slightly below the top to leave room
    for the bow. Generated from an ellipse + explicit ear cells so it
    stays editable in one place."""
    head: set[tuple[int, int]] = set()
    cx, cy = 7.5, 8.5
    rx, ry = 6.7, 5.7
    for y in range(DISPLAY_SIZE):
        for x in range(DISPLAY_SIZE):
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            if dx * dx + dy * dy <= 1.0:
                head.add((x, y))
    # Ears
    head.update({
        (3, 2), (4, 2), (3, 3), (4, 3), (5, 3),
        (10, 2), (11, 2), (11, 3), (12, 3), (13, 3),
    })
    return head


HEAD_PIXELS = _build_head_pixels()

# Eyes — keyed by blink state.
EYE_OPEN_PIXELS = {(5, 6), (5, 7), (10, 6), (10, 7)}
EYE_HALF_PIXELS = {(4, 7), (5, 7), (6, 7), (9, 7), (10, 7), (11, 7)}
EYE_CLOSED_PIXELS = EYE_HALF_PIXELS  # closed reads identically at this scale

EYES_BY_STATE = {
    "open": EYE_OPEN_PIXELS,
    "half": EYE_HALF_PIXELS,
    "closed": EYE_CLOSED_PIXELS,
}

NOSE_OUTLINE_PIXELS = {(7, 9), (8, 9)}
NOSE_FILL_PIXELS = {(7, 10), (8, 10)}

# Whiskers extend outside the face on both sides, with a slight angle.
WHISKER_PIXELS = {
    # Left side
    (0, 6), (1, 6), (2, 6), (3, 6),
    (0, 8), (1, 8), (2, 8), (3, 8),
    (0, 10), (1, 10), (2, 11), (3, 11),
    # Right side
    (12, 6), (13, 6), (14, 6), (15, 6),
    (12, 8), (13, 8), (14, 8), (15, 8),
    (12, 11), (13, 11), (14, 10), (15, 10),
}

BOW_PIXELS = {
    (11, 0), (12, 0), (13, 0),
    (10, 1), (11, 1), (12, 1), (13, 1), (14, 1),
    (10, 2), (11, 2), (12, 2), (13, 2), (14, 2),
    (11, 3), (12, 3), (13, 3),
}
BOW_KNOT_HIGHLIGHT = (12, 1)

SPARKLE_PIXELS = {(14, 0), (15, 1), (14, 2)}


def build_frame(blink_state: str) -> Image.Image:
    """Compose one frame at native 16×16 resolution."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), BG)
    pixels = img.load()

    # 1. Head + ears
    for x, y in HEAD_PIXELS:
        pixels[x, y] = WHITE

    # 2. Bow (overlays the top-right of the head)
    for x, y in BOW_PIXELS:
        pixels[x, y] = BOW_RED
    pixels[BOW_KNOT_HIGHLIGHT] = BOW_HIGHLIGHT

    # 3. Eyes
    for x, y in EYES_BY_STATE[blink_state]:
        pixels[x, y] = BLACK

    # 4. Nose
    for x, y in NOSE_OUTLINE_PIXELS:
        pixels[x, y] = BLACK
    for x, y in NOSE_FILL_PIXELS:
        pixels[x, y] = NOSE

    # 5. Whiskers (drawn last so they sit on top of the face edge)
    for x, y in WHISKER_PIXELS:
        pixels[x, y] = WHISKER

    # 6. Sparkle on the bow
    for x, y in SPARKLE_PIXELS:
        pixels[x, y] = SPARKLE

    return img


# ── Blink state machine ────────────────────────────────────────────

class KittyState:
    """Cached pre-rendered frames plus the blink-state queue."""

    def __init__(self):
        self.frames = {
            "open": build_frame("open"),
            "half": build_frame("half"),
            "closed": build_frame("closed"),
        }
        self.next_blink = 0.0       # filled in lazily on first frame
        self.blink_queue: list[tuple[str, float]] = []  # (state, until)
        self._initialised = False

    def _schedule_next(self, now: float) -> None:
        """Pick the monotonic time at which the next blink should start."""
        self.next_blink = now + random.uniform(
            BLINK_MIN_INTERVAL, BLINK_MAX_INTERVAL
        )


def make_state() -> KittyState:
    """Build the per-run state for the kitty demo."""
    return KittyState()


def _enqueue_blink(queue: list[tuple[str, float]], start: float) -> float:
    """Append one full blink (half → closed → half → open) and return the
    monotonic time at which the open phase will be reached."""
    t = start
    queue.append(("half", t + BLINK_HALF_DURATION)); t += BLINK_HALF_DURATION
    queue.append(("closed", t + BLINK_CLOSE_DURATION)); t += BLINK_CLOSE_DURATION
    queue.append(("half", t + BLINK_HALF_DURATION)); t += BLINK_HALF_DURATION
    queue.append(("open", t))
    return t


def render(ctx: FrameContext) -> Image.Image:
    """Pick the right pre-rendered frame for the current blink phase."""
    s: KittyState = ctx.state
    now = ctx.t  # seconds since demo start (monotonic)

    if not s._initialised:
        s._schedule_next(now)
        s._initialised = True

    # Schedule a new blink (or double-blink) when the queue is empty.
    if not s.blink_queue and now >= s.next_blink:
        t = _enqueue_blink(s.blink_queue, now)
        if random.random() < DOUBLE_BLINK_CHANCE:
            t = _enqueue_blink(s.blink_queue, t + DOUBLE_BLINK_GAP)
        s._schedule_next(t)

    # Drain expired phases (loop in case multiple expired in one frame).
    while s.blink_queue and now >= s.blink_queue[0][1]:
        s.blink_queue.pop(0)

    state_name = s.blink_queue[0][0] if s.blink_queue else "open"
    return s.frames[state_name]


if __name__ == "__main__":
    run_demo(
        name="kitty",
        description="Hello Kitty face with random eye blinks.",
        target_fps=TARGET_FPS,
        render=render,
        state_factory=make_state,
    )
