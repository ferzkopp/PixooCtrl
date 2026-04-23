"""
Snake game simulation for the Divoom Pixoo 16x16.

An endless auto-playing snake game with simple AI.  A green snake
chases multi-colored food targets, growing longer with each meal.
When it collides with itself it plays a death animation, pauses,
and restarts.
"""

import random
import signal
import sys
import time
from collections import deque

from PIL import Image

from pixoo import Pixoo

DISPLAY_SIZE = 16
TARGET_FPS = 8
FRAME_DELAY = 1.0 / TARGET_FPS

NUM_FOOD = 3
INITIAL_LENGTH = 3
RESTART_PAUSE = 2.5  # seconds to show score screen
DEATH_FPS = 20       # faster framerate during death animation
DEATH_FRAME_DELAY = 1.0 / DEATH_FPS

# Directions: (dx, dy)
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)
DIRECTIONS = [UP, DOWN, LEFT, RIGHT]

# Colors
SNAKE_HEAD = (80, 255, 80)
SNAKE_BODY = (0, 180, 0)
SNAKE_TAIL = (0, 120, 0)
BACKGROUND = (0, 0, 0)
DEATH_COLOR = (255, 40, 20)
DEATH_WHITE = (255, 255, 255)
SCORE_COLOR = (255, 255, 255)
SCORE_BG = (0, 0, 0)

# Tiny 3x5 pixel font for digits 0-9
DIGIT_FONT = {
    '0': [0b111, 0b101, 0b101, 0b101, 0b111],
    '1': [0b010, 0b110, 0b010, 0b010, 0b111],
    '2': [0b111, 0b001, 0b111, 0b100, 0b111],
    '3': [0b111, 0b001, 0b111, 0b001, 0b111],
    '4': [0b101, 0b101, 0b111, 0b001, 0b001],
    '5': [0b111, 0b100, 0b111, 0b001, 0b111],
    '6': [0b111, 0b100, 0b111, 0b101, 0b111],
    '7': [0b111, 0b001, 0b010, 0b010, 0b010],
    '8': [0b111, 0b101, 0b111, 0b101, 0b111],
    '9': [0b111, 0b101, 0b111, 0b001, 0b111],
}

FOOD_COLORS = [
    (255, 40, 40),     # red
    (255, 200, 0),     # yellow
    (40, 100, 255),    # blue
    (255, 0, 200),     # magenta
    (0, 220, 220),     # cyan
    (255, 120, 0),     # orange
    (200, 80, 255),    # purple
]


class SnakeGame:
    """Auto-playing snake on a 16x16 grid."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Set up a fresh game."""
        cx, cy = DISPLAY_SIZE // 2, DISPLAY_SIZE // 2
        self.body = deque()
        for i in range(INITIAL_LENGTH):
            self.body.appendleft((cx - i, cy))
        self.direction = RIGHT
        self.alive = True
        self.food: list[tuple[tuple[int, int], tuple[int, int, int]]] = []
        self._place_food(NUM_FOOD)

    def _random_empty_cell(self) -> tuple[int, int] | None:
        """Find a random cell not occupied by the snake or food."""
        occupied = set(self.body)
        occupied.update(pos for pos, _ in self.food)
        free = [
            (x, y)
            for x in range(DISPLAY_SIZE)
            for y in range(DISPLAY_SIZE)
            if (x, y) not in occupied
        ]
        return random.choice(free) if free else None

    def _place_food(self, count: int = 1):
        """Place *count* new food items on empty cells."""
        for _ in range(count):
            cell = self._random_empty_cell()
            if cell is None:
                break
            color = random.choice(FOOD_COLORS)
            self.food.append((cell, color))

    # ── AI ─────────────────────────────────────────────────────────

    def _is_safe(self, pos: tuple[int, int]) -> bool:
        """Check whether a position is in-bounds and not on the snake."""
        x, y = pos
        if not (0 <= x < DISPLAY_SIZE and 0 <= y < DISPLAY_SIZE):
            return False
        return pos not in set(self.body)

    def _opposite(self, d: tuple[int, int]) -> tuple[int, int]:
        return (-d[0], -d[1])

    def _flood_fill_size(self, start: tuple[int, int], blocked: set) -> int:
        """Count reachable cells from *start*, avoiding *blocked*."""
        visited = set()
        stack = [start]
        while stack:
            pos = stack.pop()
            if pos in visited:
                continue
            x, y = pos
            if not (0 <= x < DISPLAY_SIZE and 0 <= y < DISPLAY_SIZE):
                continue
            if pos in blocked:
                continue
            visited.add(pos)
            for dx, dy in DIRECTIONS:
                stack.append((x + dx, y + dy))
        return len(visited)

    def choose_direction(self):
        """Simple AI: move toward the nearest food while avoiding traps."""
        head = self.body[0]
        hx, hy = head
        body_set = set(self.body)

        # Candidate directions (exclude reverse to avoid instant death)
        opposite = self._opposite(self.direction)
        candidates = [d for d in DIRECTIONS if d != opposite]

        # Filter to safe moves
        safe = []
        for d in candidates:
            nx, ny = hx + d[0], hy + d[1]
            if self._is_safe((nx, ny)):
                safe.append(d)

        if not safe:
            # No safe move — will die next step
            return

        # Find nearest food
        nearest_food = None
        best_dist = float("inf")
        for (fx, fy), _ in self.food:
            dist = abs(fx - hx) + abs(fy - hy)
            if dist < best_dist:
                best_dist = dist
                nearest_food = (fx, fy)

        # Score each safe direction
        def score(d):
            nx, ny = hx + d[0], hy + d[1]
            s = 0
            # Prefer moving closer to food
            if nearest_food:
                fx, fy = nearest_food
                new_dist = abs(fx - nx) + abs(fy - ny)
                s -= new_dist * 10  # lower distance = higher score
            # Penalize moves that lead to small enclosed areas
            blocked = body_set - {self.body[-1]}  # tail will move
            blocked.add(head)
            space = self._flood_fill_size((nx, ny), blocked)
            s += space
            return s

        best = max(safe, key=score)
        self.direction = best

    # ── Step ───────────────────────────────────────────────────────

    def step(self) -> bool:
        """Advance one tick.  Returns False if the snake dies."""
        if not self.alive:
            return False

        self.choose_direction()

        hx, hy = self.body[0]
        dx, dy = self.direction
        new_head = (hx + dx, hy + dy)

        # Wall collision — wrap around
        nx, ny = new_head
        nx %= DISPLAY_SIZE
        ny %= DISPLAY_SIZE
        new_head = (nx, ny)

        # Self collision (check before moving so tail hasn't left yet)
        if new_head in set(list(self.body)[:-1]):
            self.alive = False
            return False

        self.body.appendleft(new_head)

        # Check food
        eaten = False
        for i, (fpos, _) in enumerate(self.food):
            if fpos == new_head:
                self.food.pop(i)
                self._place_food(1)
                eaten = True
                break

        if not eaten:
            self.body.pop()  # remove tail

        return True


def body_color(index: int, length: int) -> tuple[int, int, int]:
    """Gradient from head color to tail color."""
    if index == 0:
        return SNAKE_HEAD
    t = index / max(1, length - 1)
    return (
        int(SNAKE_BODY[0] + (SNAKE_TAIL[0] - SNAKE_BODY[0]) * t),
        int(SNAKE_BODY[1] + (SNAKE_TAIL[1] - SNAKE_BODY[1]) * t),
        int(SNAKE_BODY[2] + (SNAKE_TAIL[2] - SNAKE_BODY[2]) * t),
    )


def render_game(game: SnakeGame) -> Image.Image:
    """Draw the current game state."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), BACKGROUND)
    pixels = img.load()

    # Draw food
    for (fx, fy), color in game.food:
        pixels[fx, fy] = color

    # Draw snake body (tail first so head draws on top)
    length = len(game.body)
    for i, (sx, sy) in reversed(list(enumerate(game.body))):
        pixels[sx, sy] = body_color(i, length)

    return img


def render_death_frame(game: SnakeGame, step: int) -> Image.Image | None:
    """Death animation: turn red, then erase segments tail-to-head.

    The snake stays red throughout.  Disappearing segments flash white
    for one frame.  The head flickers between bright red and white.
    Returns None when the animation is finished.
    """
    body_list = list(game.body)
    total = len(body_list)
    flash_frames = 4  # initial red flash phase
    erase_frames = total  # one segment removed per frame
    total_frames = flash_frames + erase_frames

    if step >= total_frames:
        return None

    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), BACKGROUND)
    pixels = img.load()

    # Draw food (stays visible)
    for (fx, fy), color in game.food:
        pixels[fx, fy] = color

    if step < flash_frames:
        # Flash phase: entire snake red, head flickers white
        for i, (sx, sy) in enumerate(body_list):
            if i == 0 and step % 2 == 1:
                pixels[sx, sy] = DEATH_WHITE
            else:
                pixels[sx, sy] = DEATH_COLOR
    else:
        # Erase phase: remove one segment from tail each frame
        erased = step - flash_frames
        remaining = body_list[: max(0, total - erased)]

        # The segment about to disappear flashes white
        vanish_idx = len(remaining)  # index in body_list
        if vanish_idx < total:
            vx, vy = body_list[vanish_idx]
            pixels[vx, vy] = DEATH_WHITE

        # Draw remaining segments in red; head flickers
        for i, (sx, sy) in enumerate(remaining):
            if i == 0 and step % 2 == 1:
                pixels[sx, sy] = DEATH_WHITE
            else:
                pixels[sx, sy] = DEATH_COLOR

    return img


def render_score(length: int) -> Image.Image:
    """Render the snake length as a number centered on a black screen."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), SCORE_BG)
    pixels = img.load()

    text = str(length)
    char_w = 4  # 3px glyph + 1px gap
    total_w = len(text) * char_w - 1  # no trailing gap
    start_x = (DISPLAY_SIZE - total_w) // 2
    start_y = (DISPLAY_SIZE - 5) // 2  # 5px tall digits

    for ci, ch in enumerate(text):
        glyph = DIGIT_FONT.get(ch)
        if glyph is None:
            continue
        ox = start_x + ci * char_w
        for row in range(5):
            for col in range(3):
                if glyph[row] & (1 << (2 - col)):
                    px, py = ox + col, start_y + row
                    if 0 <= px < DISPLAY_SIZE and 0 <= py < DISPLAY_SIZE:
                        pixels[px, py] = SCORE_COLOR

    return img


def run(preview: bool = False):
    """Main loop: run the snake game and push frames to the Pixoo."""
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_signal)

    pixoo = None
    if not preview:
        pixoo = Pixoo.from_config()
        pixoo.connect()
        pixoo.set_brightness(70)
        print(f"Connected to Pixoo at {pixoo.mac_address}")

    game = SnakeGame()
    frame_count = 0
    games_played = 0

    print("Snake game running. Press Ctrl+C to stop.")

    try:
        last_time = time.monotonic()
        while running:
            frame_start = time.monotonic()

            alive = game.step()

            if alive:
                display_img = render_game(game)
            else:
                # Death animation (faster framerate)
                snake_len = len(game.body)
                death_step = 0
                while running:
                    anim_start = time.monotonic()
                    display_img = render_death_frame(game, death_step)
                    if display_img is None:
                        break

                    if pixoo:
                        pixoo.draw_pil_image(display_img)
                    elif preview:
                        display_img.save(
                            f"snake_preview_{frame_count:04d}.png"
                        )

                    frame_count += 1
                    death_step += 1

                    elapsed = time.monotonic() - anim_start
                    remaining = DEATH_FRAME_DELAY - elapsed
                    if remaining > 0:
                        time.sleep(remaining)

                # Show score screen
                if running:
                    score_img = render_score(snake_len)
                    if pixoo:
                        pixoo.draw_pil_image(score_img)
                    elif preview:
                        score_img.save(
                            f"snake_preview_{frame_count:04d}.png"
                        )
                    frame_count += 1
                    time.sleep(RESTART_PAUSE)

                games_played += 1
                print(
                    f"  Game {games_played} over — "
                    f"snake length was {snake_len}"
                )
                game.reset()
                continue

            if pixoo:
                pixoo.draw_pil_image(display_img)
            elif preview:
                if frame_count % 8 == 0:
                    display_img.save(
                        f"snake_preview_{frame_count:04d}.png"
                    )
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
