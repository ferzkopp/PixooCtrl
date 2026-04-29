"""
Snake game simulation for the Divoom Pixoo 16x16.

An endless auto-playing snake game with three rotating AI strategies.
A green snake chases multi-coloured food targets and grows with each
meal. When it collides with itself a death animation plays, the final
length is shown briefly, and the next game starts — each game is
preceded by a 1 s title screen showing an icon for the strategy about
to play.

AI strategies (rotated in order):
  * floodfill — greedy 1-step lookahead. Myopic; traps itself easily.
  * astar     — A* shortest path to nearest food, tail-chase fallback.
  * lookahead — A* + virtual-snake safety check (only commit if we can
                still reach our tail after eating), with a longest-path-
                toward-tail survival fallback. Strongest of the three.
"""

import heapq
import random
import time
from collections import deque

from PIL import Image

from demo_runner import FrameContext, main as run_demo

DISPLAY_SIZE = 16

# ── Tick rates ─────────────────────────────────────────────────────
# DemoRunner drives the loop at RENDER_FPS; the game state machine
# advances on its own internal timer for each phase.
RENDER_FPS = 30
GAME_TICK_HZ = 8        # how often the snake moves while alive
DEATH_TICK_HZ = 20      # death animation runs faster
SCORE_TICK_HZ = 20      # score screen redraw rate (drives the transitions)
GAME_TICK_INTERVAL = 1.0 / GAME_TICK_HZ
DEATH_TICK_INTERVAL = 1.0 / DEATH_TICK_HZ
SCORE_TICK_INTERVAL = 1.0 / SCORE_TICK_HZ

# Score screen has three sub-phases: show the just-finished score, play
# a short transition animation, then show the highscore. The 16x16 panel
# is too small to fit both at once, so we cycle them.
SCORE_SHOW_SECONDS = 2.0
SCORE_TRANSITION_SECONDS = 0.5
HIGHSCORE_SHOW_SECONDS = 2.0
SCORE_PAUSE_SECONDS = (
    SCORE_SHOW_SECONDS + SCORE_TRANSITION_SECONDS + HIGHSCORE_SHOW_SECONDS
)

# Vertical positions for the score / highscore layouts. Glyphs are 5px
# tall; SCORE_ALONE_Y centres a single line, HS_LABEL_Y / HS_NUMBER_Y
# stack "HS" above the number with a 2px gap.
SCORE_ALONE_Y = 6
HS_LABEL_Y = 2
HS_NUMBER_Y = 9

# ── Game shape ─────────────────────────────────────────────────────
NUM_FOOD = 4
INITIAL_LENGTH = 3

# ── Death animation ────────────────────────────────────────────────
DEATH_FLASH_FRAMES = 4   # initial all-red flash before the erase phase
HEAD_FLICKER_PERIOD = 2  # head alternates white/red on this period

# Directions: (dx, dy)
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)
DIRECTIONS = [UP, DOWN, LEFT, RIGHT]

# ── Colors ─────────────────────────────────────────────────────────
SNAKE_HEAD = (80, 255, 80)
SNAKE_BODY = (0, 180, 0)
SNAKE_TAIL = (0, 120, 0)
BACKGROUND = (0, 0, 0)
DEATH_COLOR = (255, 40, 20)
DEATH_WHITE = (255, 255, 255)
SCORE_COLOR = (255, 255, 255)
# Highscore label/value: dimmer than the current score so the eye reads the
# top line first. A cool cyan distinguishes it from the warm celebratory
# colour used when the current run sets a new high.
HIGHSCORE_COLOR = (0, 140, 180)
HIGHSCORE_NEW_COLOR = (255, 200, 0)  # gold — used when current run >= HS
SCORE_BG = (0, 0, 0)

# AI scoring weights
DISTANCE_WEIGHT = 10  # subtracted per Manhattan unit to nearest food

# AI strategy identifiers. The demo cycles through these on each new
# game so the display shows visibly different playstyles over time:
#   * "floodfill" — greedy 1-step lookahead, score = -dist + reachable area.
#   * "astar"     — A* shortest-path to nearest food; falls back to chasing
#                   the tail when no path exists, then to any safe move.
#   * "lookahead" — A* to food + virtual-snake safety check (only commit
#                   if we can still reach our tail after eating), with a
#                   longest-path-toward-tail survival fallback. This is the
#                   strongest of the three and reliably outscores the others
#                   on long runs because it refuses moves that would trap it.
AI_FLOODFILL = "floodfill"
AI_ASTAR = "astar"
AI_LOOKAHEAD = "lookahead"
AI_STRATEGIES = (AI_FLOODFILL, AI_ASTAR, AI_LOOKAHEAD)

# ── Title screen ───────────────────────────────────────────────────
# Shown for TITLE_SECONDS before each new game so the viewer can tell
# which AI is about to play. Each strategy has its own 16x16 icon and
# accent colour.
TITLE_SECONDS = 1.0
TITLE_TICK_HZ = 30
TITLE_TICK_INTERVAL = 1.0 / TITLE_TICK_HZ

# Tiny 3x5 pixel font for digits 0-9 plus the 'H' and 'S' glyphs needed
# for the highscore label. Kept inline so this demo has no extra asset
# files; for any other glyphs use PIL's default font.
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
    'H': [0b101, 0b101, 0b111, 0b101, 0b101],
    'S': [0b111, 0b100, 0b111, 0b001, 0b111],
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

    def __init__(self, ai: str = AI_FLOODFILL):
        """Create a fresh game using the named AI strategy."""
        if ai not in AI_STRATEGIES:
            raise ValueError(f"Unknown AI strategy: {ai!r}")
        self.ai = ai
        self.reset()

    def reset(self):
        """Reset to a fresh game: short snake centred and heading right."""
        cx, cy = DISPLAY_SIZE // 2, DISPLAY_SIZE // 2
        self.body = deque()
        for i in range(INITIAL_LENGTH):
            self.body.appendleft((cx - i, cy))
        self.direction = RIGHT
        self.alive = True
        self.food: list[tuple[tuple[int, int], tuple[int, int, int]]] = []
        self._place_food(NUM_FOOD)

    def _random_empty_cell(self) -> tuple[int, int] | None:
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
        for _ in range(count):
            cell = self._random_empty_cell()
            if cell is None:
                break
            color = random.choice(FOOD_COLORS)
            self.food.append((cell, color))

    # ── AI ─────────────────────────────────────────────────────────

    def _is_safe(self, pos: tuple[int, int]) -> bool:
        x, y = pos
        if not (0 <= x < DISPLAY_SIZE and 0 <= y < DISPLAY_SIZE):
            return False
        return pos not in set(self.body)

    def _opposite(self, d: tuple[int, int]) -> tuple[int, int]:
        return (-d[0], -d[1])

    def _flood_fill_size(self, start: tuple[int, int], blocked: set) -> int:
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
        """Pick the next heading using the configured AI strategy."""
        if self.ai == AI_ASTAR:
            self._choose_direction_astar()
        elif self.ai == AI_LOOKAHEAD:
            self._choose_direction_lookahead()
        else:
            self._choose_direction_floodfill()

    def _choose_direction_floodfill(self):
        """Greedy 1-step AI: head toward nearest food, avoid trapping."""
        head = self.body[0]
        hx, hy = head
        body_set = set(self.body)

        opposite = self._opposite(self.direction)
        candidates = [d for d in DIRECTIONS if d != opposite]
        safe = [d for d in candidates if self._is_safe((hx + d[0], hy + d[1]))]

        if not safe:
            return  # no escape — will die next step

        nearest_food = None
        best_dist = float("inf")
        for (fx, fy), _ in self.food:
            dist = abs(fx - hx) + abs(fy - hy)
            if dist < best_dist:
                best_dist = dist
                nearest_food = (fx, fy)

        def score(d):
            nx, ny = hx + d[0], hy + d[1]
            s = 0
            if nearest_food:
                fx, fy = nearest_food
                s -= (abs(fx - nx) + abs(fy - ny)) * DISTANCE_WEIGHT
            blocked = body_set - {self.body[-1]}  # tail will move
            blocked.add(head)
            s += self._flood_fill_size((nx, ny), blocked)
            return s

        self.direction = max(safe, key=score)

    # ── A* pathfinding AI ─────────────────────────────────────────
    #
    # Classic snake AI: compute the actual shortest path from head to the
    # nearest food, treating the snake's body (minus the tail, which will
    # move) as obstacles. If no path exists we fall back to chasing the
    # tail — the body is guaranteed to remain a connected loop, so heading
    # toward the moving tail keeps options open. If even that is blocked
    # we pick any safe neighbour (or give up and let the snake die).

    def _astar(
        self,
        start: tuple[int, int],
        goal: tuple[int, int],
        blocked: set,
    ) -> list[tuple[int, int]] | None:
        """Return path from start → goal as a list of cells, or None."""
        if start == goal:
            return [start]

        def h(p):
            return abs(p[0] - goal[0]) + abs(p[1] - goal[1])

        open_heap: list[tuple[int, int, tuple[int, int]]] = []
        counter = 0
        heapq.heappush(open_heap, (h(start), counter, start))
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        g_score: dict[tuple[int, int], int] = {start: 0}

        while open_heap:
            _, _, current = heapq.heappop(open_heap)
            if current == goal:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path
            cx, cy = current
            for dx, dy in DIRECTIONS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < DISPLAY_SIZE and 0 <= ny < DISPLAY_SIZE):
                    continue
                neighbour = (nx, ny)
                # The goal cell itself may be in `blocked` if the food sits
                # on a body cell (shouldn't happen, but be defensive); allow
                # entering it regardless.
                if neighbour in blocked and neighbour != goal:
                    continue
                tentative = g_score[current] + 1
                if tentative < g_score.get(neighbour, 1 << 30):
                    came_from[neighbour] = current
                    g_score[neighbour] = tentative
                    counter += 1
                    heapq.heappush(
                        open_heap, (tentative + h(neighbour), counter, neighbour)
                    )
        return None

    def _choose_direction_astar(self):
        head = self.body[0]
        hx, hy = head
        body_set = set(self.body)
        # Tail will vacate this turn (unless we eat), so don't treat it as
        # an obstacle for the search.
        tail = self.body[-1]
        blocked = body_set - {tail}

        opposite = self._opposite(self.direction)

        # 1) Try A* to the nearest reachable food (by path length, not
        #    Manhattan distance — they can differ once the body is long).
        best_path: list[tuple[int, int]] | None = None
        for (fx, fy), _ in self.food:
            path = self._astar(head, (fx, fy), blocked)
            if path is not None and (
                best_path is None or len(path) < len(best_path)
            ):
                best_path = path

        # 2) Fall back: chase the tail to stay alive.
        if best_path is None and len(self.body) > 1:
            # Treat the tail as the goal; allow stepping onto it because it
            # will have moved by the time we arrive.
            tail_blocked = body_set - {tail}
            best_path = self._astar(head, tail, tail_blocked)

        if best_path and len(best_path) >= 2:
            nx, ny = best_path[1]
            new_dir = (nx - hx, ny - hy)
            if new_dir != opposite and self._is_safe((nx, ny)):
                self.direction = new_dir
                return

        # 3) Last resort: any safe non-reverse move, preferring the one
        #    that maximises reachable area (so we don't pick a tight pocket).
        candidates = [d for d in DIRECTIONS if d != opposite]
        safe = [d for d in candidates if self._is_safe((hx + d[0], hy + d[1]))]
        if not safe:
            return
        blocked_for_score = body_set - {tail}
        blocked_for_score.add(head)
        self.direction = max(
            safe,
            key=lambda d: self._flood_fill_size((hx + d[0], hy + d[1]), blocked_for_score),
        )

    # ── Lookahead AI: A* + virtual-snake safety check ─────────────
    #
    # The two simpler strategies above die because they decide based only
    # on the *current* board. This one looks one full path ahead:
    #
    #   1. A* to the nearest reachable food.
    #   2. *Simulate* eating it — fast-forward the snake along that path
    #      and grow by one. From the resulting (virtual) head, try to A*
    #      back to the (virtual) tail. If a path exists, the body still
    #      forms a connected loop the snake can chase forever, so the
    #      move is provably safe and we commit to it.
    #   3. If no food path is safe, *survive* by heading toward our own
    #      tail along the longest path we can find. Buying time lets the
    #      body shrink (figuratively) and frees up new routes.
    #   4. Last resort: any safe move maximising flood-fill area.
    #
    # The longest-path search is NP-hard in general; we approximate by
    # picking the safe neighbour whose shortest path to the tail is the
    # *longest* — i.e. the one that keeps the most buffer between head
    # and tail. Cheap and works well in practice on a 16×16.

    def _simulate_eat(
        self, path: list[tuple[int, int]]
    ) -> deque:
        """Return the body deque after virtually following `path` and eating at the end."""
        virtual = deque(self.body)
        # Intermediate steps: move (grow head, drop tail).
        for cell in path[1:-1]:
            virtual.appendleft(cell)
            virtual.pop()
        # Final step lands on the food: grow head, keep tail.
        virtual.appendleft(path[-1])
        return virtual

    def _path_length(
        self, start: tuple[int, int], goal: tuple[int, int], blocked: set
    ) -> int:
        """Length of shortest path start→goal, or -1 if unreachable."""
        path = self._astar(start, goal, blocked)
        return -1 if path is None else len(path)

    def _choose_direction_lookahead(self):
        head = self.body[0]
        hx, hy = head
        body_set = set(self.body)
        tail = self.body[-1]
        opposite = self._opposite(self.direction)

        # 1) Find the shortest A* path to any food.
        blocked = body_set - {tail}
        best_path: list[tuple[int, int]] | None = None
        for (fx, fy), _ in self.food:
            path = self._astar(head, (fx, fy), blocked)
            if path is not None and (
                best_path is None or len(path) < len(best_path)
            ):
                best_path = path

        # 2) Virtual-snake safety check: only commit to the food path if,
        #    after eating, we can still reach our tail.
        if best_path is not None and len(best_path) >= 2:
            virtual = self._simulate_eat(best_path)
            v_head = virtual[0]
            v_tail = virtual[-1]
            v_blocked = set(virtual) - {v_tail}
            if v_head == v_tail or self._astar(v_head, v_tail, v_blocked) is not None:
                nx, ny = best_path[1]
                new_dir = (nx - hx, ny - hy)
                if new_dir != opposite and self._is_safe((nx, ny)):
                    self.direction = new_dir
                    return

        # 3) Survival mode: pick the safe neighbour with the *longest*
        #    shortest-path back to the tail. This approximates the longest
        #    head→tail path and keeps the body uncoiled.
        candidates = [d for d in DIRECTIONS if d != opposite]
        safe = [d for d in candidates if self._is_safe((hx + d[0], hy + d[1]))]
        if not safe:
            return

        if len(self.body) > 1:
            tail_blocked_base = body_set - {tail}

            def survival_score(d):
                nx, ny = hx + d[0], hy + d[1]
                # Block the head's current cell so the search must route
                # through the rest of the board, not back through us.
                blk = set(tail_blocked_base)
                blk.add(head)
                blk.discard((nx, ny))
                dist = self._path_length((nx, ny), tail, blk)
                if dist < 0:
                    # Unreachable — heavily penalise but keep flood-fill
                    # as a tiebreaker so we still pick the roomiest dead-end.
                    area = self._flood_fill_size((nx, ny), blk)
                    return (-1, area)
                return (dist, 0)

            best = max(safe, key=survival_score)
            if survival_score(best)[0] >= 0:
                self.direction = best
                return

        # 4) Last resort: maximise reachable area.
        blocked_for_score = body_set - {tail}
        blocked_for_score.add(head)
        self.direction = max(
            safe,
            key=lambda d: self._flood_fill_size((hx + d[0], hy + d[1]), blocked_for_score),
        )

    # ── Step ───────────────────────────────────────────────────────

    def step(self) -> bool:
        """Advance one tick. Returns False if the snake dies."""
        if not self.alive:
            return False

        self.choose_direction()

        hx, hy = self.body[0]
        dx, dy = self.direction
        nx, ny = hx + dx, hy + dy
        new_head = (nx, ny)

        # Wall collision — the playfield boundary is a hard block on all
        # sides. If the AI had no safe move available it kept its previous
        # heading; walking off the edge kills the snake.
        if not (0 <= nx < DISPLAY_SIZE and 0 <= ny < DISPLAY_SIZE):
            self.alive = False
            return False

        # Self collision (check before moving so tail hasn't left yet)
        if new_head in set(list(self.body)[:-1]):
            self.alive = False
            return False

        self.body.appendleft(new_head)

        eaten = False
        for i, (fpos, _) in enumerate(self.food):
            if fpos == new_head:
                self.food.pop(i)
                self._place_food(1)
                eaten = True
                break

        if not eaten:
            self.body.pop()

        return True


def body_color(index: int, length: int) -> tuple[int, int, int]:
    """Colour for the snake segment at ``index`` (0 = head, len-1 = tail)."""
    if index == 0:
        return SNAKE_HEAD
    t = index / max(1, length - 1)
    return (
        int(SNAKE_BODY[0] + (SNAKE_TAIL[0] - SNAKE_BODY[0]) * t),
        int(SNAKE_BODY[1] + (SNAKE_TAIL[1] - SNAKE_BODY[1]) * t),
        int(SNAKE_BODY[2] + (SNAKE_TAIL[2] - SNAKE_BODY[2]) * t),
    )


def render_game(game: SnakeGame) -> Image.Image:
    """Render the live game: food first, then the snake's body and head."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), BACKGROUND)
    pixels = img.load()

    for (fx, fy), color in game.food:
        pixels[fx, fy] = color

    length = len(game.body)
    for i, (sx, sy) in reversed(list(enumerate(game.body))):
        pixels[sx, sy] = body_color(i, length)

    return img


def render_death_frame(
    death_body: list[tuple[int, int]],
    food: list[tuple[tuple[int, int], tuple[int, int, int]]],
    step: int,
) -> Image.Image | None:
    """Death animation: red flash, then erase tail-to-head."""
    total = len(death_body)
    erase_frames = total
    total_frames = DEATH_FLASH_FRAMES + erase_frames

    if step >= total_frames:
        return None

    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), BACKGROUND)
    pixels = img.load()

    for (fx, fy), color in food:
        pixels[fx, fy] = color

    if step < DEATH_FLASH_FRAMES:
        for i, (sx, sy) in enumerate(death_body):
            if i == 0 and step % HEAD_FLICKER_PERIOD == 1:
                pixels[sx, sy] = DEATH_WHITE
            else:
                pixels[sx, sy] = DEATH_COLOR
    else:
        erased = step - DEATH_FLASH_FRAMES
        remaining = death_body[: max(0, total - erased)]
        vanish_idx = len(remaining)
        if vanish_idx < total:
            vx, vy = death_body[vanish_idx]
            pixels[vx, vy] = DEATH_WHITE
        for i, (sx, sy) in enumerate(remaining):
            if i == 0 and step % HEAD_FLICKER_PERIOD == 1:
                pixels[sx, sy] = DEATH_WHITE
            else:
                pixels[sx, sy] = DEATH_COLOR

    return img


def _draw_text(
    pixels,
    text: str,
    color: tuple[int, int, int],
    y: int,
    kern: int = 1,
    x_offset: int = 0,
) -> None:
    """Draw `text` horizontally centered on row `y` using DIGIT_FONT.

    `x_offset` shifts the whole string by N pixels (used by the score
    screen knock-off animation). Glyphs missing from the font are
    silently skipped, and any pixel outside the display is clipped.
    """
    glyphs = [(ch, DIGIT_FONT.get(ch)) for ch in text]
    glyphs = [(ch, g) for ch, g in glyphs if g is not None]
    if not glyphs:
        return
    total_w = len(glyphs) * 3 + max(0, len(glyphs) - 1) * kern
    start_x = (DISPLAY_SIZE - total_w) // 2 + x_offset
    for ci, (_, glyph) in enumerate(glyphs):
        ox = start_x + ci * (3 + kern)
        for row in range(5):
            for col in range(3):
                if glyph[row] & (1 << (2 - col)):
                    px, py = ox + col, y + row
                    if 0 <= px < DISPLAY_SIZE and 0 <= py < DISPLAY_SIZE:
                        pixels[px, py] = color


def _ease_in_out(t: float) -> float:
    """Smoothstep easing for the score-screen transitions."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _render_score_only(length: int, color: tuple) -> Image.Image:
    """Just the just-finished score, vertically centred."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), SCORE_BG)
    _draw_text(img.load(), str(length), color, y=SCORE_ALONE_Y)
    return img


def _render_highscore_view(
    highscore: int,
    color: tuple,
    x_offset: int = 0,
) -> Image.Image:
    """\"HS\" label above the number, both in the same colour."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), SCORE_BG)
    pixels = img.load()
    _draw_text(pixels, "HS", color, y=HS_LABEL_Y, x_offset=x_offset)
    _draw_text(pixels, str(highscore), color, y=HS_NUMBER_Y, x_offset=x_offset)
    return img


def _render_knockoff(length: int, highscore: int, t: float) -> Image.Image:
    """Slide the old score off to the left while the HS view slides in.

    Used when the just-finished run is lower than the highscore — the
    score is being "knocked off" to make room for the standing record.
    """
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), SCORE_BG)
    pixels = img.load()
    eased = _ease_in_out(t)
    score_off = -int(round(eased * (DISPLAY_SIZE + 2)))
    hs_off = int(round((1.0 - eased) * (DISPLAY_SIZE + 2)))
    _draw_text(pixels, str(length), SCORE_COLOR, y=SCORE_ALONE_Y, x_offset=score_off)
    _draw_text(pixels, "HS", HIGHSCORE_COLOR, y=HS_LABEL_Y, x_offset=hs_off)
    _draw_text(pixels, str(highscore), HIGHSCORE_COLOR, y=HS_NUMBER_Y, x_offset=hs_off)
    return img


def _render_promote(length: int, t: float) -> Image.Image:
    """Morph the centred score into the HS view.

    Used when the just-finished run ties or beats the highscore: the
    number colour shifts toward gold and slides down into the HS
    number-row position while the "HS" label drops in from above.
    """
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), SCORE_BG)
    pixels = img.load()
    eased = _ease_in_out(t)
    # Number slides from centred (SCORE_ALONE_Y) down to the HS row.
    y_num = int(round(SCORE_ALONE_Y + (HS_NUMBER_Y - SCORE_ALONE_Y) * eased))
    num_color = _lerp_color(SCORE_COLOR, HIGHSCORE_NEW_COLOR, eased)
    _draw_text(pixels, str(length), num_color, y=y_num)
    # "HS" label drops in from just above the screen to its final row.
    label_start_y = -5
    y_label = int(round(label_start_y + (HS_LABEL_Y - label_start_y) * eased))
    _draw_text(pixels, "HS", HIGHSCORE_NEW_COLOR, y=y_label)
    return img


def render_score_frame(
    length: int,
    highscore: int,
    elapsed: float,
) -> Image.Image:
    """Pick which sub-frame of the score screen to render at `elapsed`.

    Timeline:
      [0, SCORE_SHOW)                      → score alone
      [SCORE_SHOW, SCORE_SHOW+TRANSITION)  → knock-off OR promote
      [..., SCORE_PAUSE_SECONDS)           → "HS" label + highscore
    """
    new_record = length >= highscore and length > 0
    score_color = HIGHSCORE_NEW_COLOR if new_record else SCORE_COLOR
    hs_color = HIGHSCORE_NEW_COLOR if new_record else HIGHSCORE_COLOR

    if elapsed < SCORE_SHOW_SECONDS:
        return _render_score_only(length, score_color)

    transition_end = SCORE_SHOW_SECONDS + SCORE_TRANSITION_SECONDS
    if elapsed < transition_end:
        t = (elapsed - SCORE_SHOW_SECONDS) / SCORE_TRANSITION_SECONDS
        if new_record:
            return _render_promote(length, t)
        return _render_knockoff(length, highscore, t)

    return _render_highscore_view(highscore, hs_color)


# ── Title screen icons ─────────────────────────────────────────────
#
# Each AI gets a distinctive icon and accent colour shown for ~1 s
# before the game starts. Icons are stored as 16-line strings where
# '#' marks an on-pixel and any other char (typically '.') is off.
#
#   floodfill → water droplet (the AI "floods" outward from the head)
#   astar     → five-pointed star (the literal A* algorithm)
#   lookahead → eye (the AI "looks ahead" before committing to a move)
#
# A small fade-in plus a gentle brightness pulse keeps the title
# screen feeling alive instead of static.

_TITLE_ICONS: dict[str, list[str]] = {
    AI_FLOODFILL: [
        "................",
        ".......##.......",
        ".......##.......",
        "......####......",
        "......####......",
        ".....######.....",
        "....########....",
        "...##########...",
        "...##########...",
        "..############..",
        "..############..",
        "..############..",
        "...##########...",
        "....########....",
        ".....######.....",
        "................",
    ],
    AI_ASTAR: [
        "................",
        ".......##.......",
        ".......##.......",
        "......####......",
        "......####......",
        ".##############.",
        "..############..",
        "...##########...",
        "....########....",
        "....########....",
        "...###.##.###...",
        "..##...##...##..",
        ".##....##....##.",
        ".#.....##.....#.",
        "................",
        "................",
    ],
    AI_LOOKAHEAD: [
        "................",
        "................",
        "................",
        ".....######.....",
        "...##########...",
        "..####....####..",
        ".###..####..###.",
        ".##..######..##.",
        ".##..######..##.",
        ".###..####..###.",
        "..####....####..",
        "...##########...",
        ".....######.....",
        "................",
        "................",
        "................",
    ],
}

_TITLE_COLORS: dict[str, tuple[int, int, int]] = {
    AI_FLOODFILL: (60, 160, 255),    # water blue
    AI_ASTAR:     (255, 215, 0),     # gold star
    AI_LOOKAHEAD: (120, 255, 140),   # bright green ("smart" snake)
}


def render_title_frame(ai: str, elapsed: float) -> Image.Image:
    """Render the pre-game title screen for `ai` at `elapsed` seconds.

    The icon fades in over the first ~150 ms and pulses gently for the
    remainder, giving the screen some motion without distracting from
    the symbol itself.
    """
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), BACKGROUND)
    pixels = img.load()
    sprite = _TITLE_ICONS.get(ai)
    if sprite is None:
        return img
    base = _TITLE_COLORS.get(ai, (255, 255, 255))

    # Fade-in over the first 0.15 s, then a gentle 2 Hz brightness pulse.
    fade_in = min(1.0, elapsed / 0.15)
    pulse = 0.85 + 0.15 * abs(
        ((elapsed * 2.0) % 2.0) - 1.0
    )  # triangle wave 0.85 ↔ 1.00
    intensity = fade_in * pulse
    color = (
        int(base[0] * intensity),
        int(base[1] * intensity),
        int(base[2] * intensity),
    )

    for y, row in enumerate(sprite):
        for x, ch in enumerate(row):
            if ch == "#" and 0 <= x < DISPLAY_SIZE and 0 <= y < DISPLAY_SIZE:
                pixels[x, y] = color
    return img


# ── State machine driving the demo ─────────────────────────────────

class SnakeState:
    PHASE_TITLE = "title"
    PHASE_ALIVE = "alive"
    PHASE_DYING = "dying"
    PHASE_SCORE = "score"

    def __init__(self):
        """Initialise the demo state machine on the title screen."""
        # Start with flood-fill; the demo cycles through strategies on
        # each restart so viewers see all behaviours over a long session.
        self._ai_index = 0
        self.game = SnakeGame(ai=AI_STRATEGIES[self._ai_index])
        self.phase = self.PHASE_TITLE
        self.title_started = time.monotonic()
        self.last_tick = 0.0
        self.death_step = 0
        self.death_body: list[tuple[int, int]] = []
        self.death_food: list = []
        self.score_started = 0.0
        # Frozen score/highscore values shown on the score screen — the
        # snapshot is taken at the moment of death so the rendered
        # numbers don't change mid-transition.
        self.score_length = 0
        self.score_highscore = 0
        self.games_played = 0
        # Session-only highscore — reset whenever the demo restarts.
        self.highscore = 0
        self.last_image: Image.Image | None = None
        print(f"  Snake AI: {self.game.ai}")

    def next_ai(self) -> str:
        """Advance to and return the next AI strategy in the rotation."""
        self._ai_index = (self._ai_index + 1) % len(AI_STRATEGIES)
        return AI_STRATEGIES[self._ai_index]


def make_state() -> SnakeState:
    """Build the per-run state for the snake demo."""
    return SnakeState()


def render(ctx: FrameContext) -> Image.Image | None:
    """Drive the title → alive → dying → score state machine and return the next frame."""
    s: SnakeState = ctx.state
    now = time.monotonic()

    if s.phase == SnakeState.PHASE_TITLE:
        elapsed = now - s.title_started
        if elapsed >= TITLE_SECONDS:
            s.phase = SnakeState.PHASE_ALIVE
            s.last_tick = now
            s.last_image = render_game(s.game)
            return s.last_image
        if now - s.last_tick < TITLE_TICK_INTERVAL and s.last_image is not None:
            return None
        s.last_tick = now
        s.last_image = render_title_frame(s.game.ai, elapsed)
        return s.last_image

    if s.phase == SnakeState.PHASE_ALIVE:
        if now - s.last_tick < GAME_TICK_INTERVAL and s.last_image is not None:
            return None
        s.last_tick = now
        alive = s.game.step()
        if not alive:
            s.phase = SnakeState.PHASE_DYING
            s.death_step = 0
            s.death_body = list(s.game.body)
            s.death_food = list(s.game.food)
            s.last_tick = now
            # fall through to render the dying phase this frame
        else:
            s.last_image = render_game(s.game)
            return s.last_image

    if s.phase == SnakeState.PHASE_DYING:
        if now - s.last_tick < DEATH_TICK_INTERVAL and s.last_image is not None:
            return None
        s.last_tick = now
        img = render_death_frame(s.death_body, s.death_food, s.death_step)
        s.death_step += 1
        if img is None:
            # Animation complete → go to score screen
            snake_len = len(s.death_body)
            s.games_played += 1
            new_record = snake_len > s.highscore
            if snake_len > s.highscore:
                s.highscore = snake_len
            tag = " (NEW HIGHSCORE!)" if new_record else ""
            print(
                f"  Game {s.games_played} over (AI: {s.game.ai}) — "
                f"length {snake_len}, HS {s.highscore}{tag}"
            )
            s.score_length = snake_len
            s.score_highscore = s.highscore
            s.score_started = now
            s.phase = SnakeState.PHASE_SCORE
            s.last_tick = 0.0  # force an immediate score-frame render
            # fall through so the first score frame renders this tick
        else:
            s.last_image = img
            return s.last_image

    if s.phase == SnakeState.PHASE_SCORE:
        elapsed = now - s.score_started
        if elapsed >= SCORE_PAUSE_SECONDS:
            next_ai = s.next_ai()
            s.game = SnakeGame(ai=next_ai)
            print(f"  Starting next game with AI: {next_ai}")
            s.phase = SnakeState.PHASE_TITLE
            s.title_started = now
            s.last_tick = 0.0  # force an immediate title-frame render
            s.last_image = render_title_frame(s.game.ai, 0.0)
            return s.last_image
        if now - s.last_tick < SCORE_TICK_INTERVAL and s.last_image is not None:
            return None
        s.last_tick = now
        s.last_image = render_score_frame(
            s.score_length, s.score_highscore, elapsed
        )
        return s.last_image

    return s.last_image


if __name__ == "__main__":
    run_demo(
        name="snake",
        description="Auto-playing snake game for the Pixoo 16x16.",
        target_fps=RENDER_FPS,
        render=render,
        state_factory=make_state,
    )
