"""
Starfield warp effect for the Divoom Pixoo 16x16.

Classic "flying through space" animation — stars stream outward from the
center as short radial streaks, brightening as they approach the edges
with a warm yellow tint at the leading tip.
"""

import math
import random

from PIL import Image

from demo_runner import FrameContext, main as run_demo

DISPLAY_SIZE = 16
CENTER = DISPLAY_SIZE / 2.0
TARGET_FPS = 30

# Number of stars in flight at once.
NUM_STARS = 30

# Maximum simulated z-depth. Larger = stars take longer to reach the viewer.
MAX_DEPTH = 32.0

# Star "warp" speed in z-units per frame. Higher = faster trip through space.
WARP_SPEED = 0.4

# Below this z we recycle the star (it "passed" the viewer).
NEAR_CLIP = 0.2

# Random delay (in frames) inserted before respawning a star, so the two
# streaks don't fire in lockstep.
RESPAWN_DELAY_RANGE = (4, 24)

# Brightness ramp from center (dim) to edge (bright). Higher exponent =
# more of the streak's life is spent dim; lower = brighter sooner. The
# floor keeps even the spawn pixel clearly visible on a 16x16 panel.
BRIGHTNESS_GAMMA = 1.4
MIN_BRIGHTNESS_FLOOR = 0.05

# Streak length in pixels at the screen edge (closest stars). Stars near the
# center render as a single pixel; this scales up to ~STREAK_MAX at the edge.
STREAK_MAX = 4

# Lateral offset (in world units) at which a star is seeded. Must be small
# relative to MAX_DEPTH so the projection (x/z * CENTER) starts near 0,0
# and grows outward as z shrinks. With radius=1.5 and z=32, the projection
# is ~0.4 px from center; by z≈1.5 it reaches the screen edge.
SPAWN_RADIUS = 1.5

# Yellow tint applied to the leading tip — full red & green, reduced blue.
TIP_BLUE_SCALE = 0.45
# How much dimmer each step of the trail is relative to the tip.
TRAIL_FALLOFF = 0.55

# Warp center Lissajous parameters. The vanishing point traces a smooth
# Lissajous figure inside a bounded region around the screen middle, simulating
# a ship gently steering left/right/up/down on a repeating curve.
# Frequencies a and b should be small co-prime-ish values for a pleasing
# non-degenerate path; the phase offset keeps x and y out of lockstep.
WANDER_AMPLITUDE_X = 4.0     # max horizontal offset (pixels) from middle
WANDER_AMPLITUDE_Y = 3.0     # max vertical offset (pixels) from middle
WANDER_FREQ_X = 0.0013        # radians/frame for x component
WANDER_FREQ_Y = 0.0019        # radians/frame for y component (slightly faster)
WANDER_PHASE = math.pi / 2   # quarter-turn offset → ellipse-like figure-8

# Solid red center dot (single pixel) marking the current warp vanishing point.
# Base color is ~20% dimmer than full red so the pulse has headroom to breathe.
CENTER_DOT_COLOR = (204, 32, 32)
# Pulsation: brightness multiplier drifts smoothly between PULSE_MIN and 1.0
# via a low-pass filtered random target, so the dot feels alive but never
# strobes harshly.
CENTER_DOT_PULSE_MIN = 0.45
CENTER_DOT_PULSE_LERP = 0.08      # how quickly current value chases target
CENTER_DOT_TARGET_RETARGET = 0.05  # per-frame chance of picking a new target

MAX_RADIUS = math.hypot(CENTER, CENTER)


class WarpCenter:
    """Vanishing point that traces a Lissajous figure around screen middle."""

    def __init__(self):
        """Start the wandering vanishing point at screen middle, fully bright."""
        self.t = 0.0
        self.x = CENTER
        self.y = CENTER
        # Pulsation state: current brightness multiplier and the value it's
        # smoothly chasing. Re-randomized occasionally for organic flicker.
        self.pulse = 1.0
        self.pulse_target = 1.0

    def update(self):
        """Advance one frame: move along the Lissajous path and ease the pulse."""
        self.t += 1.0
        self.x = CENTER + WANDER_AMPLITUDE_X * math.sin(WANDER_FREQ_X * self.t + WANDER_PHASE)
        self.y = CENTER + WANDER_AMPLITUDE_Y * math.sin(WANDER_FREQ_Y * self.t)
        # Occasionally pick a new brightness target.
        if random.random() < CENTER_DOT_TARGET_RETARGET:
            self.pulse_target = random.uniform(CENTER_DOT_PULSE_MIN, 1.0)
        # Ease the current value toward the target (exponential smoothing).
        self.pulse += (self.pulse_target - self.pulse) * CENTER_DOT_PULSE_LERP


class Star:
    """A star with 3D position projected onto the 2D display."""

    def __init__(self):
        """Spawn the star somewhere along its lifecycle (see ``reset``)."""
        self.delay = 0
        self.reset(initial=True)

    def reset(self, initial: bool = False):
        """(Re)seed the star with a random direction.

        If ``initial`` is true the z-depth is randomised across the full
        lifecycle so the screen isn't empty for the first few seconds;
        otherwise the star starts at MAX_DEPTH after a short respawn delay.
        """
        # Pick a random outward direction. The lateral offset is small so the
        # projection starts within ~half a pixel of dead center and grows
        # outward as z decreases — the star's full life is on-screen.
        angle = random.uniform(0.0, 2.0 * math.pi)
        self.x = math.cos(angle) * SPAWN_RADIUS
        self.y = math.sin(angle) * SPAWN_RADIUS
        if initial:
            # Spread initial stars across the full lifecycle so the field
            # already has streaks at every depth from frame 0 — otherwise
            # they all start fresh at MAX_DEPTH and bunch together, leaving
            # a long empty gap before the first respawns kick in.
            self.z = random.uniform(NEAR_CLIP + 1.0, MAX_DEPTH)
            self.delay = 0
        else:
            self.z = MAX_DEPTH
            # Stagger respawns so the streaks don't pulse together.
            self.delay = random.randint(*RESPAWN_DELAY_RANGE)

    def update(self, speed: float, cx: float, cy: float):
        """Advance the star by ``speed`` z-units; recycle when it leaves view."""
        if self.delay > 0:
            self.delay -= 1
            return
        self.z -= speed
        if self.z <= NEAR_CLIP:
            self.reset()
            return
        sx, sy = self.project(cx, cy)
        # Recycle only when the star is well past the screen so the trail has
        # room to extend out of view rather than popping at the edge.
        margin = DISPLAY_SIZE
        if not (-margin <= sx < DISPLAY_SIZE + margin
                and -margin <= sy < DISPLAY_SIZE + margin):
            self.reset()

    @property
    def visible(self) -> bool:
        """False while the star is waiting out its respawn delay."""
        return self.delay == 0

    def project(self, cx: float, cy: float) -> tuple[float, float]:
        """Project the star's 3D position onto screen-space pixels."""
        return cx + self.x / self.z * CENTER, cy + self.y / self.z * CENTER


def render_stars(stars: list[Star], center: WarpCenter) -> Image.Image:
    """Render every visible star as a radial streak with a yellow tip."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), (0, 0, 0))
    pixels = img.load()

    cx, cy = center.x, center.y

    for star in stars:
        if not star.visible or star.z <= NEAR_CLIP:
            continue

        sx, sy = star.project(cx, cy)
        # Don't skip when the tip is off-screen — the trail (extending back
        # toward the warp center) may still be visible. The per-pixel bounds
        # check inside the streak loop below clips properly.

        # Radial distance from the (wandering) warp center drives both
        # brightness and streak length.
        dx = sx - cx
        dy = sy - cy
        r = math.hypot(dx, dy)
        edge_t = min(1.0, r / MAX_RADIUS)

        tip_brightness = MIN_BRIGHTNESS_FLOOR + (
            1.0 - MIN_BRIGHTNESS_FLOOR
        ) * (edge_t ** BRIGHTNESS_GAMMA)

        # 1 pixel near center, up to STREAK_MAX at the edge.
        length = 1 + int(round((STREAK_MAX - 1) * edge_t))

        # Unit vector pointing outward; trail steps backward toward center.
        if r > 0.01:
            ux, uy = dx / r, dy / r
        else:
            ux = uy = 0.0

        for i in range(length):
            px = int(round(sx - ux * i))
            py = int(round(sy - uy * i))
            if not (0 <= px < DISPLAY_SIZE and 0 <= py < DISPLAY_SIZE):
                continue

            step_b = tip_brightness * (TRAIL_FALLOFF ** i)
            if i == 0:
                # Yellow-tinted leading tip.
                color = (
                    int(255 * step_b),
                    int(255 * step_b),
                    int(255 * step_b * TIP_BLUE_SCALE),
                )
            else:
                v = int(255 * step_b)
                color = (v, v, v)

            # Don't overwrite a brighter pixel already drawn (other star's tip).
            existing = pixels[px, py]
            if sum(existing) < sum(color):
                pixels[px, py] = color

    _draw_center_dot(pixels, cx, cy, center.pulse)
    return img


def _draw_center_dot(pixels, cx: float, cy: float, pulse: float) -> None:
    """Draw the warp center as a solid single red pixel scaled by `pulse`."""
    px = int(round(cx))
    py = int(round(cy))
    if 0 <= px < DISPLAY_SIZE and 0 <= py < DISPLAY_SIZE:
        r, g, b = CENTER_DOT_COLOR
        pixels[px, py] = (
            int(r * pulse),
            int(g * pulse),
            int(b * pulse),
        )


def make_state() -> dict:
    """Build the per-run state: NUM_STARS stars and one wandering warp centre."""
    # Star.__init__ already staggers respawn delays for the initial spawn.
    return {
        "stars": [Star() for _ in range(NUM_STARS)],
        "center": WarpCenter(),
    }


def render(ctx: FrameContext) -> Image.Image:
    """Step the warp centre and every star, then render the frame."""
    stars: list[Star] = ctx.state["stars"]
    center: WarpCenter = ctx.state["center"]
    center.update()
    for star in stars:
        star.update(WARP_SPEED, center.x, center.y)
    return render_stars(stars, center)


if __name__ == "__main__":
    run_demo(
        name="starfield",
        description="Starfield warp effect for the Pixoo 16x16.",
        target_fps=TARGET_FPS,
        render=render,
        state_factory=make_state,
    )
