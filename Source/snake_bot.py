#!/usr/bin/env python3
"""Snake bot: plays snake.py from the outside, through tmux.

Influenced by an earlier project: typesafe-snake by sorrycc
(github.com/sorrycc/typesafe-snake). No code was copied from it.

It never touches the game's code or memory. It only does what a human could:
  * looks at the screen   -> `tmux capture-pane -p -e`  (the screen text plus its colours)
  * presses arrow keys    -> `tmux send-keys Up|Down|Left|Right`

The game draws every cell as a coloured block, so the bot reads the board by
background colour: yellow = head, cyan = neck, green = body, blue = tail, red = food.

Two players are available:
  jev        (default) Each new frame is turned into a text grid and sent to
             TypeSafe's Jev model, which picks the move. Jev sees only the board
             and the rules, and is offered only the three legal moves (never the
             reversal). If the snake has already moved on by the time Jev answers,
             the answer is thrown away and the snake carries on straight.
  algorithm  The built-in path-finding strategy (no API calls).

Jev's API key is read from TYPESAFE_API_KEY, or else from --key-file
(default: jev_key.txt in the directory the bot is started from). When the
launcher opens tmux it passes a TYPESAFE_API_KEY key on to the bot in a private
one-time file, since a tmux session doesn't always inherit the variable.
Each call to Jev waits at most 1 second. The run stops with a message saying why
if Jev reports the account is out of credits, rejects the API key, or fails
MAX_ERRORS_IN_A_ROW calls in a row (network errors, error replies, or replies in
an unexpected shape; late answers don't count). If the bot stops with an error,
its pane stays open showing the message until Enter is pressed.

Usage:
    ./snake_bot.py                       Open a tmux session with the game on top and the
                                         bot's stats underneath, and watch Jev play.
    ./snake_bot.py --games 5             Play 5 games, show a summary, then wait for Q.
    ./snake_bot.py --player algorithm    Watch the built-in strategy instead.
    ./snake_bot.py --no-log              Don't keep a log.
    ./snake_bot.py --target PANE         Play a game already running in tmux pane PANE.

Logging (on by default): each run writes <player>_<date>_<time>.jsonl in the
directory the bot is started from (--log-dir changes it), one JSON record per line:
  session_start  first line of the log: the version of snake_bot.py and of
                 snake.py, then every setting that shapes the run: game speed and speed-up, board
                 size, start length, bot player and rules, the exact instructions
                 and options sent to Jev, model, price, and software versions
  move           every decision: game and move number, score, the board as sent,
                 the options offered, Jev's answer (choice, confidence, probabilities),
                 response time, input tokens, cost, whether the answer arrived too
                 late (and was dropped) and why: "snake moved" (the board changed before
                 the answer came) or "too close" (it came under 40 ms before the next
                 move, so its key could land a step late), the key actually pressed, and
                 whether the key pressed on the previous move reached the game a
                 step late (the snake wasn't heading that way on the next board)
  game_end       score, moves, failed Jev calls (api_errors), how it ended (wall/body, read from the game-over
                 screen; and whether the last key, a safe turn, arrived too late), keys
                 that reached the game a step late, the final board, late answers (by reason), measured
                 seconds per move, tokens, cost, and how many screen reads were skipped
                 because they caught the game mid-redraw (snake not fully or consistently drawn)
  session_end    games played, average and best score, total tokens and total cost,
                 failed Jev calls across the whole run (api_errors, counting any
                 game cut short), where the best game's screen was saved, and why the run stopped
                 early, if it did (a game cut short this way is not counted)
Records are written after the key press, so logging never delays a move.
The same records also go, as plain text, to <player>_<date>_<time>.txt for reading
in a text editor: the versions and settings, one line per move, each game's result
and final board, and the run's totals.
Cost uses TypeSafe's published price of $0.042 per million input tokens.

Best-game screen: when a run ends, the game-over screen of its highest-scoring
game (the first one, if several tie) is saved next to the log, with the same name:
  <player>_<date>_<time>_best.html   open in a browser, in the game's colours
  <player>_<date>_<time>_best.ans    show in a terminal with: cat <file>
These are saved even with --no-log.

Quit by pressing Q in the game pane; the bot exits when the game does.
"""

import argparse
import html
import http.client
import json
import os
import random
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

try:  # the game's settings: starting length (to check a captured frame is complete)
    from snake import SPEEDUP, START_DELAY, START_LENGTH  # and speed (for the key deadline)
except Exception:  # noqa: BLE001
    START_LENGTH, START_DELAY, SPEEDUP = 4, 0.3, 1.0

# A key must reach the game this long before its next step, or it could land one
# step late (after the snake has already moved on). Covers the bot's polling and
# capture delay plus the time tmux takes to deliver the key.
KEY_MARGIN = 0.040  # 25 ms proved too little: a 268 ms answer's key once landed a step late

VERSION = "1.5"

HERE = Path(__file__).resolve().parent
SESSION = "snakebot"
DEFAULT_KEY_FILE = "jev_key.txt"  # looked for in the directory the bot is started from
JEV_HOST, JEV_PATH = "api.typesafe.ai", "/v1/systemone"
REQUEST_TIMEOUT = 1.0  # seconds; answers after 0.3 s are dropped anyway, so don't wait long
# Stop the run after this many failed Jev calls in a row (about 3 s of play),
# rather than letting the snake run blind into walls game after game.
MAX_ERRORS_IN_A_ROW = 10
BILLING_URL = "https://console.typesafe.ai/setting"
PRICE_PER_TOKEN = 0.042 / 1_000_000  # TypeSafe's published Jev price: $0.042 per million input tokens

UP, DOWN, LEFT, RIGHT = (0, -1), (0, 1), (-1, 0), (1, 0)
DIRS = (UP, DOWN, LEFT, RIGHT)
KEY_NAMES = {UP: "Up", DOWN: "Down", LEFT: "Left", RIGHT: "Right"}
NAME_DIRS = {v: k for k, v in KEY_NAMES.items()}

CELL_W = 2  # the game draws each grid cell two terminal columns wide

# Standard terminal colour numbers the game paints each cell's background with.
RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN = 1, 2, 3, 4, 5, 6
FOOD, BODY, HEAD, TAIL, NECK, DEAD = RED, GREEN, YELLOW, BLUE, CYAN, MAGENTA


# --------------------------------------------------------------------------- tmux

def tmux(*args, check=True):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)


def capture(target):
    """Return the pane's screen with colour codes, or None if the pane is gone."""
    r = tmux("capture-pane", "-p", "-e", "-t", target, check=False)
    return r.stdout if r.returncode == 0 else None


def press(target, key):
    tmux("send-keys", "-t", target, key, check=False)


# ------------------------------------------------------------------ screen reading

SGR = re.compile(r"\x1b\[([0-9;]*)m")  # a terminal "set colour/style" code


def decode(text):
    """Split the captured screen into plain text lines and background colour lines.

    Returns (chars, colours): chars[row] is the row's text, and colours[row][col]
    is the background colour number at that column (None for the default).
    """
    chars, colours = [], []
    bg = None
    for line in text.split("\n"):
        row_chars, row_bg = [], []
        pos = 0
        for m in SGR.finditer(line + "\x1b[m"):
            for ch in line[pos:m.start()]:
                row_chars.append(ch)
                row_bg.append(bg)
            pos = m.end()
            bg = apply_sgr(m.group(1), bg)
        chars.append("".join(row_chars))
        colours.append(row_bg)
    return chars, colours


def apply_sgr(params, bg):
    """Update the current background colour from one SGR code's parameters."""
    codes = [int(p) if p else 0 for p in params.split(";")]
    i = 0
    while i < len(codes):
        c = codes[i]
        if c in (0, 49):
            bg = None
        elif 40 <= c <= 47:
            bg = c - 40
        elif 100 <= c <= 107:
            bg = c - 100
        elif c == 48 and i + 2 < len(codes) and codes[i + 1] == 5:
            bg = codes[i + 2] % 8 if codes[i + 2] < 16 else codes[i + 2]
            i += 2
        elif c in (38, 48) and i + 1 < len(codes) and codes[i + 1] == 2:
            i += 4  # 24-bit colour: not used by the game
        i += 1
    return bg


class Screen:
    """What the bot can see on one captured frame."""

    def __init__(self):
        self.cols = self.rows = 0
        self.head = self.neck = self.tail = self.food = None
        self.body = set()  # every snake cell except the head (includes neck and tail)
        self.score = 0
        self.over = self.paused = False

    def frame_id(self):
        return (self.head, self.neck, self.tail, self.food, len(self.body))

    def complete(self):
        """True if the whole snake is on screen and drawn consistently. A capture taken
        while the game is part-way through redrawing can miss cells or show some in
        their old colours (for example the neck still where it was), which would give
        the player a broken board; such reads are skipped.

        Checks: head, neck and tail are all there; the length is START_LENGTH + score;
        the neck is next to the head; and the snake is one connected chain."""
        if self.head is None or self.neck is None or self.tail is None:
            return False
        if len(self.body) + 1 != START_LENGTH + self.score:
            return False
        if self.neck not in adj(self.head):
            return False
        seen, todo = {self.head}, [self.head]  # walk the snake's cells from the head
        while todo:
            for n in adj(todo.pop()):
                if n in self.body and n not in seen:
                    seen.add(n)
                    todo.append(n)
        return len(seen) == len(self.body) + 1

    def cell_ahead(self, d):
        """What the head would move into going in direction d: "wall", "body" or
        "safe". The tail counts as safe: it moves out of the way (the snake can't be
        eating there, since food is never on the snake)."""
        x, y = self.head[0] + d[0], self.head[1] + d[1]
        if not (0 <= x < self.cols and 0 <= y < self.rows):
            return "wall"
        return "body" if (x, y) in self.body and (x, y) != self.tail else "safe"

    def crash_cause(self, pressed=None):
        """Called on the game-over screen, where the snake is shown exactly where it
        crashed from (it doesn't move when it crashes). Returns (cause, key_late):
        cause is "wall", "body" or "unknown"; key_late is True if a key pressed on
        this board would have been safe but the snake went straight instead, i.e.
        the turn reached the game too late.

        pressed: the direction of a key the bot pressed while this board was showing."""
        heading = self.heading()
        if not self.head or not heading:
            return "unknown", False
        if pressed and pressed != heading:
            turned = self.cell_ahead(pressed)
            if turned != "safe":
                return turned, False  # the turn was taken, into a wall or the body
            straight = self.cell_ahead(heading)
            return (straight if straight != "safe" else "unknown"), True
        straight = self.cell_ahead(heading)
        return (straight if straight != "safe" else "unknown"), False

    def heading(self):
        if self.head and self.neck:
            return (self.head[0] - self.neck[0], self.head[1] - self.neck[1])
        return None

    def grid_text(self):
        """The board as the text grid Jev is shown."""
        grid = [["."] * self.cols for _ in range(self.rows)]
        for x, y in self.body:
            grid[y][x] = "B"
        if self.tail:
            grid[self.tail[1]][self.tail[0]] = "T"
        if self.neck:
            grid[self.neck[1]][self.neck[0]] = "N"
        if self.food:
            grid[self.food[1]][self.food[0]] = "F"
        if self.head:
            grid[self.head[1]][self.head[0]] = "H"
        return "\n".join(" ".join(row) for row in grid)


def read_screen(text):
    chars, colours = decode(text)

    # Find the board's border: top-left, top-right and bottom-left corners.
    top = next((r for r, line in enumerate(chars) if "┌" in line), None)
    if top is None:
        return None
    left = chars[top].index("┌")
    right = chars[top].find("┐", left)
    bottom = next((r for r in range(top + 1, len(chars))
                   if chars[r][left:left + 1] == "└"), None)
    if right < 0 or bottom is None:
        return None

    s = Screen()
    s.cols = (right - left - 1) // CELL_W
    s.rows = bottom - top - 1
    for y in range(s.rows):
        row = colours[top + 1 + y]
        for x in range(s.cols):
            c = left + 1 + x * CELL_W
            colour = row[c] if c < len(row) else None
            if colour in (HEAD, DEAD):  # DEAD is the head's colour after a crash
                s.head = (x, y)
            elif colour == FOOD:
                s.food = (x, y)
            elif colour in (BODY, NECK, TAIL):
                s.body.add((x, y))
                if colour == NECK:
                    s.neck = (x, y)
                elif colour == TAIL:
                    s.tail = (x, y)

    plain = "\n".join(chars)
    m = re.search(r"Score:\s*(\d+)", plain)
    s.score = int(m.group(1)) if m else 0
    s.over = "GAME OVER" in plain or "YOU WIN" in plain
    s.paused = "PAUSED" in plain
    return s


# ---------------------------------------------------------------------- Jev player

JEV_INSTRUCTIONS = (
    "This grid shows a game of snake, {cols} columns across by {rows} rows down. "
    "Reading the grid: H marks the head, N the neck directly behind it, B the rest of the body, "
    "T the last segment, F the food, and a dot a free square. "
    "On every step the head advances one square in the chosen direction and the other segments trail behind it. "
    "Steering off the grid or onto the body ends the game. "
    "Reversing is impossible: a command pointing back at N does nothing and the snake continues ahead. "
    "Swallowing the food adds one square of length. "
    "Pick the next direction: survive and reach the food."
)
JEV_DESCRIPTIONS = {
    "Up": "Head goes one square up, to the row above.",
    "Down": "Head goes one square down, to the row below.",
    "Left": "Head goes one square left, to the column on its left.",
    "Right": "Head goes one square right, to the column on its right.",
}


def load_api_key(key_file):
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    try:
        key = Path(key_file).expanduser().read_text().strip()
    except OSError:
        key = ""
    if not key:
        sys.exit(f"No Jev API key: set TYPESAFE_API_KEY or put the key in {key_file}")
    return key


class JevStop(Exception):
    """Jev can't go on answering: the run is stopped, with this message."""


def jev_message(payload):
    """The human-readable message in a Jev error reply, if there is one."""
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("error_type") or detail)
    return str(detail if detail is not None else payload)[:300]


class JevPlayer:
    """Asks Jev for each move over one reused HTTPS connection."""

    def __init__(self, key_file, model):
        self.key = load_api_key(key_file)
        self.model = model
        self.conn = None
        self.times = []
        self.last = ""
        self.errors_in_a_row = 0
        self.stop = None  # set to a message when the run must stop; play() checks it

    def failed(self, info, last, error):
        """Record a failed call, and stop the run if too many have failed in a row."""
        self.last = last
        info["error"] = error
        self.errors_in_a_row += 1
        if self.errors_in_a_row >= MAX_ERRORS_IN_A_ROW and not self.stop:
            self.stop = (f"Jev failed {self.errors_in_a_row} calls in a row, so the run was stopped.\n"
                         f"Last error: {error}\n"
                         "Check the network connection and the TypeSafe console, then start the "
                         "bot again.")
        return None, info

    def choose(self, s):
        """Return (direction or None, info for the log) for this frame."""
        heading = s.heading()
        options = [name for name, d in NAME_DIRS.items()
                   if heading is None or d != (-heading[0], -heading[1])]
        random.shuffle(options)  # vary the order so position can't steer the answer
        board = s.grid_text()
        body = json.dumps({
            "model": self.model,
            "state": board,
            "questions": {"move": {
                "type": "choice",
                "instructions": JEV_INSTRUCTIONS.format(cols=s.cols, rows=s.rows),
                "criteria": {name: JEV_DESCRIPTIONS[name] for name in options},
            }},
        })
        info = {"board": board, "options": options}
        t = time.perf_counter()
        try:
            if self.conn is None:
                self.conn = http.client.HTTPSConnection(JEV_HOST, timeout=REQUEST_TIMEOUT)
            self.conn.request("POST", JEV_PATH, body=body, headers={
                "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            resp = self.conn.getresponse()
            payload = json.loads(resp.read() or b"{}")
        except (http.client.HTTPException, OSError, ValueError) as e:
            self.close()
            return self.failed(info, f"network error: {type(e).__name__}", f"{type(e).__name__}: {e}")
        ms = (time.perf_counter() - t) * 1000
        info["response_ms"] = round(ms, 1)
        if resp.status != 200:
            error = f"HTTP {resp.status}: {str(payload)[:200]}"
            detail = payload.get("detail") if isinstance(payload, dict) else None
            billing = resp.status == 402 or (isinstance(detail, dict)
                                             and detail.get("error_type") == "billing_error")
            if billing:  # out of credits: no point trying again
                info["error"] = error
                self.stop = ("Jev stopped the run: the TypeSafe account is out of API credits "
                             f"(HTTP {resp.status}).\n"
                             f"Jev said: {jev_message(payload)}\n"
                             f"Add credits at {BILLING_URL}, then start the bot again.")
                return None, info
            if resp.status == 401:  # the key is wrong or revoked: no point trying again
                info["error"] = error
                self.stop = ("Jev rejected the API key (HTTP 401).\n"
                             f"Jev said: {jev_message(payload)}\n"
                             "Check the key in the key file (or TYPESAFE_API_KEY), then start the bot again.")
                return None, info
            # Anything else may pass: no waiting here, the game keeps moving, so just try next move.
            return self.failed(info, f"Jev error {resp.status}", error)
        try:  # a reply in an unexpected shape is treated like a failed call, not a crash
            ans = payload["answers"]["move"]
            choice = ans["choice"]
            if choice not in options:
                raise ValueError(f"choice {choice!r} was not one of the options offered")
            usage = payload.get("usage") or {}
            tokens = int(usage.get("input_tokens", 0))
            confidence = float(ans.get("confidence", 0))
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            return self.failed(info, "unexpected reply from Jev",
                               f"unexpected reply ({type(e).__name__}: {e}): {str(payload)[:200]}")
        self.errors_in_a_row = 0
        self.times.append(ms)
        info.update(model=payload.get("model"), answer=ans, input_tokens=tokens,
                    cost_usd=tokens * PRICE_PER_TOKEN)
        self.last = f"{choice:<5} conf {confidence:.2f}  {ms:4.0f} ms"
        return NAME_DIRS[choice], info

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


# ---------------------------------------------------------------- algorithm player

class Tracker:
    """Keeps the snake's segments in order (head first), for the algorithm player.

    The screen shows the head, neck and tail, but not the order of the middle of
    the body, so we follow the snake frame by frame, and fall back to working the
    order out from the shape if we ever lose track.
    """

    def __init__(self):
        self.snake = None

    def update(self, s):
        cells = s.body | {s.head}
        old = self.snake
        if old:
            if s.head == old[0] and set(old) == cells:
                return False  # nothing moved
            if abs(s.head[0] - old[0][0]) + abs(s.head[1] - old[0][1]) == 1:
                cand = [s.head] + old
                del cand[len(cells):]
                if set(cand) == cells:
                    self.snake = cand
                    return True
        self.snake = rebuild(s.head, cells)
        return True


def rebuild(head, cells, limit=20000):
    """Find an ordering of `cells` that is a connected path starting at `head`."""
    target = len(cells)
    path, visited = [head], {head}
    stack = [iter(ordered_next(head, cells, visited))]
    steps = 0
    while stack:
        if len(path) == target:
            return path
        steps += 1
        if steps > limit:
            return None
        nxt = next(stack[-1], None)
        if nxt is None:
            stack.pop()
            visited.discard(path.pop())
            continue
        path.append(nxt)
        visited.add(nxt)
        stack.append(iter(ordered_next(nxt, cells, visited)))
    return None


def ordered_next(p, cells, visited):
    # Try the most constrained neighbour first (Warnsdorff's rule): fast in practice.
    opts = [n for n in adj(p) if n in cells and n not in visited]
    return sorted(opts, key=lambda n: sum(1 for m in adj(n) if m in cells and m not in visited))


def adj(p):
    return [(p[0] + dx, p[1] + dy) for dx, dy in DIRS]


def bfs(start, goal, blocked, cols, rows):
    """Shortest path from start to goal (excluding start), avoiding blocked cells."""
    prev = {start: None}
    q = deque([start])
    while q:
        p = q.popleft()
        if p == goal:
            path = []
            while p != start:
                path.append(p)
                p = prev[p]
            return path[::-1]
        nbrs = adj(p)
        random.shuffle(nbrs)  # vary tie-breaks so the bot doesn't get stuck in a rut
        for n in nbrs:
            if n not in prev and 0 <= n[0] < cols and 0 <= n[1] < rows and n not in blocked:
                prev[n] = p
                q.append(n)
    return None


def flood_area(start, blocked, cols, rows):
    seen, q = {start}, deque([start])
    while q:
        for n in adj(q.popleft()):
            if n not in seen and 0 <= n[0] < cols and 0 <= n[1] < rows and n not in blocked:
                seen.add(n)
                q.append(n)
    return len(seen)


def advance(snake, cell, food):
    """The snake after its head moves into `cell` (grows if it eats)."""
    return [cell] + (snake if cell == food else snake[:-1])


def tail_reachable(snake, cols, rows):
    if len(snake) < 2:
        return True
    return bfs(snake[0], snake[-1], set(snake[1:-1]), cols, rows) is not None


def plan(snake, food, cols, rows, restless):
    """Pick the next cell for the head.

    1. Take the shortest path to the food, but only if, after eating, the snake
       could still reach its own tail (so it can never trap itself).
    2. Otherwise follow its tail the long way round, buying time until a safe
       path to the food opens up.
    3. If even that fails, move wherever there is the most open space.
    """
    head = snake[0]
    blocked = set(snake[:-1])  # the tail moves out of the way this step

    if food is not None and not restless:
        path = bfs(head, food, blocked, cols, rows)
        if path:
            v = snake
            for cell in path:
                v = advance(v, cell, food)
            if tail_reachable(v, cols, rows):
                return path[0]

    moves = [n for n in adj(head)
             if 0 <= n[0] < cols and 0 <= n[1] < rows and n not in blocked]
    if not moves:
        return None

    safe = []
    for n in moves:
        v = advance(snake, n, food)
        if tail_reachable(v, cols, rows):
            d = bfs(v[0], v[-1], set(v[1:-1]), cols, rows)
            safe.append((len(d) if d else 0, n))
    if safe:
        if restless:  # been circling too long: shake things up
            return random.choice(safe)[1]
        return max(safe)[1]

    return max(moves, key=lambda n: flood_area(n, set(advance(snake, n, food)[1:]), cols, rows))


class AlgorithmPlayer:
    def __init__(self):
        self.tracker = Tracker()
        self.since_food = 0
        self.last_score = 0
        self.last = ""

    def choose(self, s):
        self.tracker.update(s)
        self.since_food = 0 if s.score > self.last_score else self.since_food + 1
        self.last_score = s.score
        snake = self.tracker.snake
        if snake is None:  # lost track of the order: play on open space alone
            options = [n for n in adj(s.head) if 0 <= n[0] < s.cols and 0 <= n[1] < s.rows
                       and n not in s.body]
            nxt = max(options, key=lambda n: flood_area(n, s.body, s.cols, s.rows), default=None)
        else:
            nxt = plan(snake, s.food, s.cols, s.rows, self.since_food > s.cols * s.rows * 2)
        info = {"board": s.grid_text()}
        if nxt is None:
            return None, info
        return (nxt[0] - s.head[0], nxt[1] - s.head[1]), info

    def new_game(self):
        self.__init__()

    def close(self):
        pass


# ----------------------------------------------------------------------- the loop

class Log:
    """Appends one JSON record per line, written straight to disk, and the same
    records as plain text to a .txt file with the same name, for people to read."""

    def __init__(self, path):
        self.path = path
        self.f = self.text = None
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.f = open(path, "a")
            text_path = Path(path).with_suffix(".txt")
            if text_path == Path(path):  # the log itself is a .txt file
                text_path = Path(path).with_name(Path(path).stem + "_readable.txt")
            self.text_path = text_path
            self.text = TextLog(open(text_path, "a"))

    def write(self, kind, **fields):
        if self.f:
            rec = {"type": kind, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), **fields}
            self.f.write(json.dumps(rec) + "\n")
            self.f.flush()
            try:
                self.text.write(rec)
            except Exception as e:  # noqa: BLE001 - the text log must never stop the bot
                self.text.out(f"(could not write this {kind} record as text: {e})")

    def close(self):
        if self.f:
            self.f.close()
            self.text.f.close()


# Columns of the move table in the text log: (header, width). Headers and values
# are both left-aligned to the same width, so each header sits right above its values.
JEV_COLUMNS = [("Time", 8), ("Move", 4), ("Score", 5), ("Offered", 18), ("Jev Chose", 9),
               ("Conf", 4), ("Up", 4), ("Down", 4), ("Left", 4), ("Right", 5), ("Reply", 7),
               ("Key Pressed", 0)]
ALGO_COLUMNS = [("Time", 8), ("Move", 4), ("Score", 5), ("Key Pressed", 0)]

ENDINGS = {"wall": "hit the wall", "body": "hit its body", "won": "won (board full)",
           "unknown": "cause unknown"}


class TextLog:
    """Writes log records as plain text: a header with the versions and settings,
    one line per move, a summary and the final board for each game, and a run summary."""

    def __init__(self, f):
        self.f = f
        self.game = None
        self.model = None
        self.is_jev = False

    def out(self, line=""):
        self.f.write(line + "\n")
        self.f.flush()

    def write(self, r):
        getattr(self, r["type"])(r)

    def session_start(self, r):
        g, bot, jev, env = r.get("game", {}), r.get("bot", {}), r.get("jev"), r.get("environment", {})
        self.is_jev = bot.get("player") == "jev"
        when = r["time"].replace("T", " ")
        self.out("=" * 100)
        self.out(f"Snake bot log    snake_bot.py {r.get('snake_bot_version')}    "
                 f"snake.py {r.get('snake_version')}    started {when}")
        self.out("=" * 100)
        player = (f"Jev (model requested: {jev.get('model_requested')})" if self.is_jev
                  else "built-in algorithm")
        self.out(f"Player:   {player}")
        self.out(f"Board:    {g.get('board_cols_seen')} x {g.get('board_rows_seen')}, "
                 f"snake starts {g.get('start_length')} long, "
                 f"{g.get('seconds_per_move_at_start')} s per move ({g.get('speed_note')})")
        self.out(f"Games:    {bot.get('games_requested')}")
        if self.is_jev:
            self.out(f"Offered:  {bot.get('moves_offered')}")
            self.out(f"Late:     {bot.get('late_answer_rule')}")
            self.out(f"Price:    ${jev.get('price_usd_per_million_input_tokens')} "
                     f"per million input tokens")
        else:
            self.out(f"Strategy: {bot.get('strategy')}")
        self.out(f"Software: Python {env.get('python')}, {env.get('tmux')}")
        if self.is_jev:
            self.out("\nInstructions sent to Jev with every board:")
            words, line = jev.get("instructions", "").split(), "   "
            for w in words:  # wrap to fit an editor window
                if len(line) + len(w) > 96:
                    self.out(line)
                    line = "   "
                line += " " + w
            self.out(line)
            self.out("\nMove lines: Offered is the order the moves were sent in; Conf is Jev's "
                     "confidence; Up Down Left Right")
            self.out("are Jev's probability for each move (- = not offered); Reply is Jev's "
                     "response time.")
            self.out("\nOption descriptions (only the three legal ones are sent):")
            for k, v in jev.get("option_descriptions", {}).items():
                self.out(f"    {k:<6} {v}")

    def move(self, r):
        if self.model is None and r.get("model"):
            # The model's full name only arrives with Jev's first answer: show it once,
            # with the run's settings, before the first game.
            self.model = r["model"]
            self.out(f"\nModel answering: {self.model}")
        if r.get("game") != self.game:
            self.game = r.get("game")
            self.out(f"\nGame {self.game}")
            self.row(JEV_COLUMNS if self.is_jev else ALGO_COLUMNS,
                     [name for name, _ in (JEV_COLUMNS if self.is_jev else ALGO_COLUMNS)])
        if r.get("model") and r["model"] != self.model:  # only if the model changes mid-run
            self.model = r["model"]
            self.out(f"  (Jev model changed to: {self.model})")
        if r.get("previous_key_landed_late"):
            self.out("  (the key pressed on the move above reached the game a step late)")
        clock = r["time"][11:]
        key = r.get("key_pressed") or "none, keeps going straight"
        if not self.is_jev:
            self.row(ALGO_COLUMNS, [clock, r.get("move"), r.get("score"), key])
            return
        offered = " ".join(r.get("options", []))
        if "error" in r:
            self.row(JEV_COLUMNS[:4], [clock, r.get("move"), r.get("score"), offered],
                     tail="no answer: " + r["error"][:60])
            return
        ans = r.get("answer", {})
        probs = ans.get("probabilities", {})
        # One column per direction ("-" = not offered), so every line has the same layout.
        cells = [f"{probs[m]:.2f}" if m in probs else "-" for m in ("Up", "Down", "Left", "Right")]
        if r.get("late"):
            why = {"snake moved": "snake already moved",
                   "too close": "too close to next move"}.get(r.get("late_reason"), "too late")
            key = f"none: late ({why}), dropped"
        elif not r.get("key_pressed"):
            key = f"none, already going {ans.get('choice', 'that way')}"
        self.row(JEV_COLUMNS, [clock, r.get("move"), r.get("score"), offered, ans.get("choice", "?"),
                               f"{ans.get('confidence', 0):.2f}", *cells,
                               f"{r.get('response_ms', 0):.0f} ms", key])

    def row(self, columns, values, tail=""):
        """One table line: every value starts where its column's header starts."""
        parts = [f"{str(v):<{width}}" for (_, width), v in zip(columns, values)]
        self.out(("  " + "  ".join(parts) + ("  " + tail if tail else "")).rstrip())

    def game_end(self, r):
        late = r.get("late_answers", 0)
        ending = ENDINGS.get(r.get("ended_by"), r.get("ended_by"))
        if r.get("crash_key_landed_late"):
            ending += " (the last key, a safe turn, reached the game too late)"
        parts = [f"score {r.get('score')}", f"{r.get('moves')} moves", ending]
        if self.is_jev:
            if "api_errors" in r:
                parts.append(f"{r['api_errors']} Jev error{'' if r['api_errors'] == 1 else 's'}")
            parts.append(f"{late} late answer{'' if late == 1 else 's'}")
            if late and "late_snake_moved" in r:
                parts[-1] += (f" ({r['late_snake_moved']} snake already moved, "
                              f"{r['late_too_close']} too close to next move)")
        if r.get("keys_landed_late"):
            parts.append(f"{r['keys_landed_late']} key{'' if r['keys_landed_late'] == 1 else 's'} "
                         "reached the game a step late")
        if r.get("incomplete_reads_skipped"):
            parts.append(f"{r['incomplete_reads_skipped']} mid-redraw screen reads skipped")
        if r.get("measured_seconds_per_move"):
            parts.append(f"{r['measured_seconds_per_move']:.3f} s per move")
        if self.is_jev:
            parts.append(f"{r.get('input_tokens', 0):,} tokens, ${r.get('cost_usd', 0):.4f}")
        self.out(f"\n  Game {r.get('game')} over: " + ", ".join(parts))
        if r.get("final_board"):
            self.out("  Final board (H head, N neck, B body, T tail, F food):")
            for row in r["final_board"].split("\n"):
                self.out("    " + row)
        self.game = None

    def session_end(self, r):
        self.out("\n" + "=" * 100)
        avg = r.get("average_score")
        self.out(f"Run finished {r['time'].replace('T', ' ')}: {r.get('games')} game(s), "
                 f"average score {avg if avg is not None else '-'}, best {r.get('best_score')}"
                 + (f" (game {r['best_game']})" if r.get("best_game") else ""))
        if self.is_jev:
            why = (f" ({r['late_snake_moved']} snake already moved, {r['late_too_close']} too close "
                   "to next move)") if r.get("late_answers") and "late_snake_moved" in r else ""
            self.out(f"Late answers {r.get('late_answers')}{why}, {r.get('input_tokens', 0):,} input tokens, "
                     f"total cost ${r.get('total_cost_usd', 0):.4f}")
            if "api_errors" in r:
                self.out(f"Jev errors {r['api_errors']} (failed calls: timeouts, network errors, error replies)")
        if r.get("stopped_early"):
            self.out("STOPPED EARLY: " + r["stopped_early"].replace("\n", "\n               "))
        if r.get("best_screen_html"):
            self.out(f"Best game's screen: {r['best_screen_html']}")
            self.out(f"                    {r['best_screen_ans']}")
        self.out("=" * 100 + "\n")


def game_settings():
    """The game's settings, read from snake.py next to this script.

    The bot only watches the screen, so it reads the same file the game was
    started from. (If snake.py is edited while a game is running, this shows
    the new values; the measured time per move in each game_end record is the
    ground truth.)
    """
    try:
        import snake
    except Exception as e:  # noqa: BLE001 - logging must never stop the bot
        return {"error": f"could not read snake.py: {e}"}
    return {
        "version": getattr(snake, "VERSION", "unknown"),
        "seconds_per_move_at_start": snake.START_DELAY,
        "speedup_per_food": snake.SPEEDUP,
        "speed_note": "constant speed" if snake.SPEEDUP == 1 else
                      f"each food multiplies the time per move by {snake.SPEEDUP}",
        "start_length": snake.START_LENGTH,
        "max_board_cols": snake.MAX_COLS,
        "max_board_rows": snake.MAX_ROWS,
        "reversal_rule": "a move straight back into the neck is ignored",
    }


def session_settings(args):
    """Everything that shapes a run, for the session_start log record (versions first)."""
    tmux_version = tmux("-V", check=False).stdout.strip()
    bot = {
        "player": args.player,
        "games_requested": args.games or "no limit",
        "frame_poll_seconds": 0.005,
    }
    jev = None
    if args.player == "jev":
        bot["moves_offered"] = "the three legal moves (never the reversal), shuffled each move"
        bot["late_answer_rule"] = ("if the snake has moved before Jev answers, or the answer "
                                   f"arrives less than {KEY_MARGIN * 1000:.0f} ms before the next "
                                   "move, the answer is dropped and the snake carries on straight")
        jev = {
            "model_requested": args.model,
            "endpoint": f"https://{JEV_HOST}{JEV_PATH}",
            "api_key_source": "TYPESAFE_API_KEY" if os.environ.get("TYPESAFE_API_KEY", "").strip()
                              else str(Path(args.key_file).expanduser()),
            "request_timeout_seconds": REQUEST_TIMEOUT,
            "instructions": JEV_INSTRUCTIONS,
            "option_descriptions": JEV_DESCRIPTIONS,
            "board_symbols": "H head, N neck, B body, T tail, F food, . empty",
            "price_usd_per_million_input_tokens": PRICE_PER_TOKEN * 1_000_000,
        }
    else:
        bot["strategy"] = "built-in path-finding (shortest safe path to food, else follow tail)"
    game = game_settings()
    return {
        "snake_bot_version": VERSION,
        "snake_version": game.pop("version", "unknown"),
        "game": game,
        "bot": bot,
        "jev": jev,
        "environment": {"python": sys.version.split()[0], "tmux": tmux_version},
    }


def play(target, max_games, hold, player, log, settings, shot_base):
    """Play until max_games games are done (0 = no limit) or the game is closed.

    With hold=True, after the last game the bot prints a summary and stays open
    until the game is closed, so the results stay on screen.

    The game-over screen of the best game is saved as shot_base + "_best.html/.ans".
    """
    is_jev = isinstance(player, JevPlayer)
    finished = False
    started = False  # session_start is logged once the board has been seen
    first_frame_t = last_frame_t = None
    # Session totals
    games = best = total_score = total_late = total_tokens = 0
    total_late_counts = {"snake moved": 0, "too close": 0}
    total_cost = 0.0
    # Current game
    moves = late = tokens = incomplete = 0
    late_counts = {"snake moved": 0, "too close": 0}
    cost = 0.0
    last_frame = prev = None
    sent_key = None  # (frame_id, direction) of the last key pressed, to check it took effect
    keys_late = 0  # keys that reached the game a step late (the turn happened one move late)
    status = ""
    best_shot = None  # the best game's final screen, saved when the run ends
    shot_paths = None
    stop_reason = None  # why Jev stopped the run early, if it did
    errors = total_errors = 0  # failed Jev calls: this game, and the whole run

    def show(msg):
        nonlocal status
        # Cut to the pane's width: a status line that wraps can't be redrawn in place.
        msg = msg[:max(shutil.get_terminal_size().columns - 1, 20)]
        if msg != status:
            status = msg
            print("\r\033[K" + msg, end="", flush=True)

    print(f"Snake bot {VERSION} ({type(player).__name__}) watching tmux pane {target}.  "
          f"Press Q in the game to quit.")
    print(f"Logging to {log.path}\n    and {log.text_path} (plain text)\n" if log.path
          else "Logging is off.\n")
    try:
        while True:
            text = capture(target)
            if text is None:
                print("\n\nGame closed.")
                break
            s = read_screen(text)
            if s is None:
                show("Waiting for the game board...")
                time.sleep(0.2)
                continue

            if not started:
                started = True
                settings["game"]["board_cols_seen"] = s.cols
                settings["game"]["board_rows_seen"] = s.rows
                if settings.get("jev"):  # log the instructions exactly as sent
                    settings["jev"]["instructions"] = JEV_INSTRUCTIONS.format(cols=s.cols, rows=s.rows)
                log.write("session_start", **settings, target=target)  # versions come first

            if s.over:
                if moves:  # only count games the bot actually played
                    games += 1
                    total_score += s.score
                    best = max(best, s.score)
                    total_late += late
                    for k in total_late_counts:
                        total_late_counts[k] += late_counts[k]
                    total_tokens += tokens
                    total_cost += cost
                    # Worked out from the game-over screen itself, which shows the snake
                    # where it crashed from (an older board the bot handled can be out
                    # of date if an answer was late).
                    pressed = sent_key[1] if sent_key and sent_key[0] == s.frame_id() else None
                    if "YOU WIN" in text:
                        cause, key_late_at_end = "won", False
                    else:
                        cause, key_late_at_end = s.crash_cause(pressed)
                    if key_late_at_end:
                        keys_late += 1
                    if best_shot is None or s.score > best_shot["score"]:  # first one wins a tie
                        best_shot = {"text": text, "game": games, "score": s.score, "cause": cause,
                                     "moves": moves, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
                    measured = None
                    if moves > 1 and first_frame_t is not None:
                        measured = round((last_frame_t - first_frame_t) / (moves - 1), 4)
                    log.write("game_end", game=games, score=s.score, moves=moves,
                              ended_by=cause, api_errors=errors, late_answers=late,
                              late_snake_moved=late_counts["snake moved"],
                              late_too_close=late_counts["too close"], keys_landed_late=keys_late,
                              crash_key_landed_late=key_late_at_end, final_board=s.grid_text(),
                              incomplete_reads_skipped=incomplete,
                              measured_seconds_per_move=measured, input_tokens=tokens,
                              cost_usd=round(cost, 6), session_total_cost_usd=round(total_cost, 6))
                    money = f"  ${cost:.4f}  (session ${total_cost:.4f})" if is_jev else ""
                    print(f"\rGame {games}: score {s.score:<3} {cause:<4} moves {moves:<4}"
                          f"{f' late {late}' if is_jev else ''}{money}"
                          f"  | avg {total_score / games:.1f} best {best}"
                          f"{f'  errors {total_errors}' if is_jev else ''}\033[K")
                    status = ""
                    if max_games and games >= max_games:
                        finished = True
                        break
                    time.sleep(1.5)
                press(target, "r")
                if hasattr(player, "new_game"):
                    player.new_game()
                moves = late = tokens = incomplete = errors = 0
                late_counts = {"snake moved": 0, "too close": 0}
                cost = 0.0
                last_frame = prev = sent_key = None
                keys_late = 0
                first_frame_t = last_frame_t = None
                time.sleep(0.3)
                continue

            if s.paused:
                show("Game paused - press P in the game to resume.")
                time.sleep(0.1)
                continue

            if s.head is None or s.frame_id() == last_frame:
                time.sleep(0.005)  # no new frame yet; poll again soon
                continue
            if not s.complete():
                incomplete += 1  # caught the game mid-redraw; read again
                time.sleep(0.002)
                continue
            last_frame = s.frame_id()
            last_frame_t = time.monotonic()
            if first_frame_t is None:
                first_frame_t = last_frame_t
            prev = s
            moves += 1
            # Did the key pressed on the previous board take effect? If the snake is
            # not now heading that way, the key reached the game after it had moved.
            key_missed = bool(sent_key) and s.heading() != sent_key[1]
            if key_missed:
                keys_late += 1
            sent_key = None

            d, info = player.choose(s)
            if "error" in info:
                errors += 1
                total_errors += 1
            tokens += info.get("input_tokens", 0)
            cost += info.get("cost_usd", 0.0)

            was_late = False
            late_reason = None  # why an answer was dropped: "snake moved" or "too close"
            if d is not None and is_jev:
                # Jev takes time to answer. If the snake has moved on meanwhile, or is
                # about to, this answer was for an old board (or its key could land a
                # step late): drop it and let the snake go straight.
                step = START_DELAY * SPEEDUP ** s.score  # the game's time per move now
                too_close = time.monotonic() - last_frame_t > step - KEY_MARGIN
                s_now = None
                for _ in range(10):  # skip reads taken mid-redraw, as above
                    now = capture(target)
                    s_now = read_screen(now) if now else None
                    if s_now is None or s_now.over or s_now.complete():
                        break
                    incomplete += 1
                    time.sleep(0.002)
                if s_now is None or s_now.frame_id() != last_frame:
                    late_reason = "snake moved"  # the board changed before the answer came
                elif too_close:
                    late_reason = "too close"  # under KEY_MARGIN left before the next move
                if late_reason:
                    late += 1
                    late_counts[late_reason] += 1
                    was_late = True
                    d = None

            heading = s.heading()
            pressed = None
            if d is not None and d != heading:
                press(target, KEY_NAMES[d])
                pressed = KEY_NAMES[d]
                sent_key = (last_frame, d)

            # Logged after the key press, so writing the log can never delay a move.
            log.write("move", game=games + 1, move=moves, score=s.score, late=was_late,
                      late_reason=late_reason, key_pressed=pressed,
                      previous_key_landed_late=key_missed, **info)
            if is_jev and player.stop:  # out of credits, bad key, or too many failures
                raise JevStop(player.stop)

            extra = ""
            if is_jev and player.times:
                extra = (f"  late {late}  errors {total_errors}  {statistics.median(player.times):.0f} ms"
                         f"  ${total_cost + cost:.4f}   last: {player.last}")
            show(f"Game {games + 1}: score {s.score}  moves {moves}{extra}")
    except JevStop as e:
        stop_reason = str(e)
        raise
    finally:
        if best_shot:
            best_shot["games"] = games
            try:
                shot_paths = save_best_screen(shot_base, best_shot,
                                              "Jev" if is_jev else "algorithm")
            except OSError as e:
                print(f"\nCould not save the best game's screen: {e}")
        log.write("session_end", games=games, average_score=round(total_score / games, 2)
                  if games else None, best_score=best, api_errors=total_errors, late_answers=total_late,
                  late_snake_moved=total_late_counts["snake moved"],
                  late_too_close=total_late_counts["too close"],
                  input_tokens=total_tokens, total_cost_usd=round(total_cost, 6),
                  best_game=best_shot["game"] if best_shot else None,
                  best_screen_html=str(shot_paths[0]) if shot_paths else None,
                  best_screen_ans=str(shot_paths[1]) if shot_paths else None,
                  stopped_early=stop_reason)
        if shot_paths and not finished:
            print(f"\nBest game's screen saved to {shot_paths[0]}")

    if finished:
        money = f", total cost ${total_cost:.4f}, Jev errors {total_errors}" if is_jev else ""
        print(f"\nFinished {games} game(s): average score {total_score / games:.1f}, "
              f"best {best}{money}.")
        if shot_paths:
            print(f"Best game (game {best_shot['game']}) screen saved to:\n"
                  f"  {shot_paths[0]}\n  {shot_paths[1]}")
        if hold:
            print("Press Q in the game to close.")
            while capture(target) is not None:  # wait until the game is closed
                time.sleep(0.5)


# ------------------------------------------------------------- best-game screen

# Colours for the HTML copy of the screen (close to a typical dark terminal theme).
HTML_COLOURS = ["#000000", "#cc0000", "#4e9a06", "#c4a000", "#3465a4", "#75507b", "#06989a", "#d3d7cf",
                "#555753", "#ef2929", "#8ae234", "#fce94f", "#729fcf", "#ad7fa8", "#34e2e2", "#eeeeec"]
HTML_FG, HTML_BG = "#d3d7cf", "#1e1e1e"


def sgr_style(params, st):
    """Update a full text style (fg, bg, bold, dim, reverse) from one SGR code."""
    codes = [int(p) if p else 0 for p in params.split(";")]
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0:
            st = {"fg": None, "bg": None, "bold": False, "dim": False, "rev": False}
        elif c == 1:
            st["bold"] = True
        elif c == 2:
            st["dim"] = True
        elif c == 22:
            st["bold"] = st["dim"] = False
        elif c == 7:
            st["rev"] = True
        elif c == 27:
            st["rev"] = False
        elif 30 <= c <= 37:
            st["fg"] = c - 30
        elif 90 <= c <= 97:
            st["fg"] = c - 90 + 8
        elif c == 39:
            st["fg"] = None
        elif 40 <= c <= 47:
            st["bg"] = c - 40
        elif 100 <= c <= 107:
            st["bg"] = c - 100 + 8
        elif c == 49:
            st["bg"] = None
        elif c in (38, 48) and i + 2 < len(codes) and codes[i + 1] == 5:
            n = codes[i + 2]
            st["fg" if c == 38 else "bg"] = n if n < 16 else None
            i += 2
        elif c in (38, 48) and i + 1 < len(codes) and codes[i + 1] == 2:
            i += 4  # 24-bit colour: not used by the game
        i += 1
    return st


def screen_to_html(text, title, caption):
    """Turn a captured screen (text with colour codes) into a standalone HTML page."""
    st = {"fg": None, "bg": None, "bold": False, "dim": False, "rev": False}
    out = []
    for line in text.split("\n"):
        pos = 0
        for m in SGR.finditer(line + "\x1b[m"):
            chunk = line[pos:m.start()]
            if chunk:
                fg = HTML_COLOURS[st["fg"]] if st["fg"] is not None else HTML_FG
                bg = HTML_COLOURS[st["bg"]] if st["bg"] is not None else None
                if st["rev"]:
                    fg, bg = bg or HTML_BG, fg
                css = [f"color:{fg}"]
                if bg:
                    css.append(f"background:{bg}")
                if st["bold"]:
                    css.append("font-weight:bold")
                if st["dim"]:
                    css.append("opacity:0.6")
                out.append(f'<span style="{";".join(css)}">{html.escape(chunk)}</span>')
            pos = m.end()
            st = sgr_style(m.group(1), st)
        out.append("\n")
    return (f"<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title>\n<style>\n"
            f"body {{ background:{HTML_BG}; color:{HTML_FG}; font-family:sans-serif; margin:2em; }}\n"
            f"h1 {{ font-size:1.2em; margin:0 0 .3em; }}\n"
            f"p {{ margin:0 0 1em; color:#aaa; }}\n"
            f"pre {{ font-family:'DejaVu Sans Mono','Liberation Mono',monospace; font-size:15px; "
            f"line-height:1.15; margin:0; }}\n"
            f"</style></head>\n<body>\n<h1>{html.escape(title)}</h1>\n<p>{html.escape(caption)}</p>\n"
            f"<pre>{''.join(out).rstrip()}</pre>\n</body></html>\n")


def save_best_screen(base, shot, player_name):
    """Save the best game's screen as base_best.html and base_best.ans. Returns the paths."""
    lines = shot["text"].split("\n")
    while lines and not SGR.sub("", lines[-1]).strip():
        lines.pop()  # drop the empty rows below the game
    text = "\n".join(lines)
    title = f"Snake: best game of the run ({player_name})"
    caption = (f"Game {shot['game']} of {shot['games']}: score {shot['score']}, "
               f"ended by {shot['cause']} after {shot['moves']} moves, {shot['time']}")
    html_path = Path(f"{base}_best.html")
    ans_path = Path(f"{base}_best.ans")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(screen_to_html(text, title, caption))
    ans_path.write_text(f"{title}\n{caption}\n\n{text}\x1b[0m\n")
    return html_path, ans_path


# --------------------------------------------------------------------- launching

def key_handoff_file(key):
    """Write the API key to a new file only this user can read, for the bot inside
    tmux to read and delete. Avoids putting the key on a command line, where other
    users of the computer could see it."""
    import tempfile
    folder = os.environ.get("XDG_RUNTIME_DIR")  # private to this user, in memory
    fd, path = tempfile.mkstemp(prefix="snake_bot_key_", dir=folder if folder and
                                os.path.isdir(folder) else None)  # created with mode 0600
    with os.fdopen(fd, "w") as f:
        f.write(key)
    return path


def launch(extra_args):
    if subprocess.run(["tmux", "has-session", "-t", SESSION], capture_output=True).returncode == 0:
        sys.exit(f"A '{SESSION}' tmux session already exists. "
                 f"Attach with: tmux attach -t {SESSION}   or end it with: tmux kill-session -t {SESSION}")

    w, h = shutil.get_terminal_size()
    # tmux's status bar takes a line once we attach; size for the space that's left.
    if tmux("show-options", "-gv", "status", check=False).stdout.strip() != "off":
        h -= 1
    py = shlex.quote(sys.executable)
    game_cmd = f"{py} {shlex.quote(str(HERE / 'snake.py'))}"

    # Create the bot pane first, then put the game above it at its final size
    # (the game sizes its board when it starts, so it must not be resized later).
    bot_pane = tmux("new-session", "-d", "-s", SESSION, "-x", str(w), "-y", str(h),
                    "-P", "-F", "#{pane_id}").stdout.strip()
    game_pane = tmux("split-window", "-b", "-t", bot_pane, "-l", str(max(h - 8, 10)),
                     "-P", "-F", "#{pane_id}", game_cmd).stdout.strip()
    bot_cmd = " ".join([py, shlex.quote(str(Path(__file__).resolve())), "--target", game_pane,
                        *map(shlex.quote, extra_args)])
    # If the bot stops with an error, keep its pane open so the message can be read
    # (otherwise tmux closes the pane at once and the message is lost).
    bot_cmd += ('; code=$?; if [ $code -ne 0 ]; then printf "\\nThe bot stopped (exit code %s). '
                'Press Enter to close this pane. " $code; read _; fi')
    tmux("respawn-pane", "-k", "-t", bot_pane, bot_cmd)
    tmux("select-pane", "-t", game_pane)

    if os.environ.get("TMUX"):
        tmux("switch-client", "-t", SESSION)
    else:
        os.execvp("tmux", ["tmux", "attach", "-t", SESSION])


def main():
    parser = argparse.ArgumentParser(description="A bot that plays snake.py through tmux.")
    parser.add_argument("--player", choices=("jev", "algorithm"), default="jev",
                        help="who picks the moves (default jev)")
    parser.add_argument("--target", help="tmux pane running the game (default: launch a new session)")
    parser.add_argument("--games", type=int, default=0, metavar="N",
                        help="number of games to play, then stop (default: keep playing until Q)")
    parser.add_argument("--hold", action="store_true", help=argparse.SUPPRESS)  # set by the launcher
    # Set by the launcher: the key from TYPESAFE_API_KEY, passed in a private file
    # that the bot reads and deletes (a tmux session may not inherit the variable).
    parser.add_argument("--key-handoff", help=argparse.SUPPRESS)
    parser.add_argument("--key-file", default=DEFAULT_KEY_FILE,
                        help=f"file holding the Jev API key (default: {DEFAULT_KEY_FILE} in the "
                             "directory the bot is started from)")
    parser.add_argument("--model", default="jev-latest", help="Jev model (default jev-latest)")
    parser.add_argument("--log", help="log file to append to (default: a new file in the log directory)")
    parser.add_argument("--log-dir", default=".",
                        help="directory for logs and best-game screens "
                             "(default: the directory the bot is started from)")
    parser.add_argument("--version", action="version", version=f"snake_bot.py {VERSION}")
    parser.add_argument("--no-log", action="store_true", help="don't keep a log")
    args = parser.parse_args()
    if args.games < 0:
        sys.exit("--games must be 0 (no limit) or more")
    # Fix the key file's full path now, relative to where the bot was started, so the
    # copy of the bot running inside tmux finds the same file.
    args.key_file = str(Path(args.key_file).expanduser().resolve())
    log_dir = Path(args.log_dir).expanduser().resolve()  # same reason: fixed before tmux starts

    if not shutil.which("tmux"):
        sys.exit("tmux is not installed. Install it with: sudo apt install tmux")

    if not args.target:
        # Check the key now, before opening tmux, so a problem is reported here.
        if args.player == "jev":
            load_api_key(args.key_file)
        extra = ["--player", args.player, "--key-file", args.key_file, "--model", args.model]
        if args.player == "jev" and os.environ.get("TYPESAFE_API_KEY", "").strip():
            extra += ["--key-handoff", key_handoff_file(os.environ["TYPESAFE_API_KEY"].strip())]
        extra += ["--games", str(args.games), "--hold", "--log-dir", str(log_dir)]
        if args.no_log:
            extra.append("--no-log")
        elif args.log:
            extra += ["--log", str(Path(args.log).resolve())]
        launch(extra)
        return

    if args.no_log:
        log_path = None
    elif args.log:
        log_path = args.log
    else:
        log_path = log_dir / f"{args.player}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    log = Log(log_path)
    # The best game's screen is saved next to the log, with the same name.
    shot_base = (Path(log_path).with_suffix("") if log_path
                 else log_dir / f"{args.player}_{time.strftime('%Y%m%d_%H%M%S')}")
    if args.key_handoff:
        try:
            os.environ["TYPESAFE_API_KEY"] = Path(args.key_handoff).read_text().strip()
        except OSError as e:
            sys.exit(f"Could not read the API key passed by the launcher: {e}")
        finally:
            Path(args.key_handoff).unlink(missing_ok=True)
    player = JevPlayer(args.key_file, args.model) if args.player == "jev" else AlgorithmPlayer()
    try:
        play(args.target, args.games, args.hold, player=player, log=log,
             settings=session_settings(args), shot_base=shot_base)
    except KeyboardInterrupt:
        print()
    except JevStop as e:
        sys.exit(f"\n\n{e}")
    finally:
        player.close()
        log.close()


if __name__ == "__main__":
    main()
