#!/usr/bin/env python3
"""Terminal Snake (version 1.1), drawn with solid colour blocks. Steer with the arrow keys.

Influenced by an earlier project: typesafe-snake by sorrycc
(github.com/sorrycc/typesafe-snake). No code was copied from it.

Controls:
    Arrow keys   steer
    P / Space    pause / resume
    R / Enter    restart after game over
    Q / Esc      quit

Colours: yellow = head, cyan = neck (segment behind the head), green = body,
blue = tail, red = food, magenta = head after a crash.
"""

import curses
import os
import random
import sys
import time
from collections import deque
from curses.textpad import rectangle

VERSION = "1.1"

MAX_COLS, MAX_ROWS = 40, 20  # board size cap (grid cells)
MIN_COLS, MIN_ROWS = 12, 6   # smallest playable board
START_LENGTH = 4
START_DELAY = 0.3           # seconds per step
SPEEDUP = 1.0                # each food multiplies the step delay by this (1.0 = constant speed)

# Each grid cell is two terminal columns wide, because terminal characters are
# about twice as tall as they are wide. This keeps the cells square.
CELL_W = 2

UP, DOWN, LEFT, RIGHT = (0, -1), (0, 1), (-1, 0), (1, 0)
KEY_DIRS = {
    curses.KEY_UP: UP,
    curses.KEY_DOWN: DOWN,
    curses.KEY_LEFT: LEFT,
    curses.KEY_RIGHT: RIGHT,
}

# Colour pair numbers and the background colour each cell type is painted with.
# The neck (the segment behind the head) and the tail get their own colours so
# that a single screen shows which way the snake is heading and where it ends.
HEAD, BODY, FOOD, DEAD, NECK, TAIL = 1, 2, 3, 4, 5, 6
CELL_COLOURS = {
    HEAD: curses.COLOR_YELLOW,
    BODY: curses.COLOR_GREEN,
    FOOD: curses.COLOR_RED,
    DEAD: curses.COLOR_MAGENTA,
    NECK: curses.COLOR_CYAN,
    TAIL: curses.COLOR_BLUE,
}


class Game:
    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.reset()

    def reset(self):
        cx, cy = self.cols // 2, self.rows // 2
        self.snake = deque((cx - i, cy) for i in range(START_LENGTH))  # [0] is the head
        self.occupied = set(self.snake)
        self.direction = RIGHT
        self.pending = deque()  # buffered turns, so quick key taps aren't lost
        self.score = 0
        self.delay = START_DELAY
        self.over = False
        self.won = False
        self.paused = False
        self.food = self._place_food()

    def _place_food(self):
        free = [
            (x, y)
            for x in range(self.cols)
            for y in range(self.rows)
            if (x, y) not in self.occupied
        ]
        return random.choice(free) if free else None

    def turn(self, d):
        last = self.pending[-1] if self.pending else self.direction
        # Ignore no-op turns and direct reversals into the snake's own neck.
        if d == last or (d[0] == -last[0] and d[1] == -last[1]):
            return
        if len(self.pending) < 2:
            self.pending.append(d)

    def step(self):
        if self.pending:
            self.direction = self.pending.popleft()
        hx, hy = self.snake[0]
        dx, dy = self.direction
        new = (hx + dx, hy + dy)

        if not (0 <= new[0] < self.cols and 0 <= new[1] < self.rows):
            self.over = True
            return

        grows = new == self.food
        tail = self.snake[-1]
        # Moving into the cell the tail is leaving this step is allowed.
        if new in self.occupied and not (new == tail and not grows):
            self.over = True
            return

        if not grows:
            self.occupied.discard(self.snake.pop())
        self.snake.appendleft(new)
        self.occupied.add(new)

        if grows:
            self.score += 1
            self.delay *= SPEEDUP
            self.food = self._place_food()
            if self.food is None:  # board completely filled
                self.over = self.won = True


def fits(stdscr, game):
    h, w = stdscr.getmaxyx()
    return h >= game.rows + 4 and w >= game.cols * CELL_W + 2


def put(stdscr, y, x, text, attr=0):
    h, w = stdscr.getmaxyx()
    if 0 <= y < h and 0 <= x < w - 1:
        try:
            stdscr.addnstr(y, x, text, w - 1 - x, attr)
        except curses.error:
            pass


def draw(stdscr, game, high):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    if not fits(stdscr, game):
        put(stdscr, 0, 0, "Terminal too small - please enlarge it (Q to quit)")
        stdscr.refresh()
        return

    board_w = game.cols * CELL_W + 2
    left = (w - board_w) // 2
    top = 1

    status = f" Score: {game.score}   High: {max(high, game.score)}   Length: {len(game.snake)}"
    put(stdscr, 0, left, status, curses.A_BOLD)
    rectangle(stdscr, top, left, top + game.rows + 1, left + board_w - 1)

    def cell(pos, kind):
        x, y = pos
        put(stdscr, top + 1 + y, left + 1 + x * CELL_W, " " * CELL_W, curses.color_pair(kind))

    if game.food:
        cell(game.food, FOOD)
    last = len(game.snake) - 1
    for i, seg in enumerate(game.snake):
        if i == 0:
            cell(seg, DEAD if game.over and not game.won else HEAD)
        elif i == 1:
            cell(seg, NECK)
        elif i == last:
            cell(seg, TAIL)
        else:
            cell(seg, BODY)

    mid_y = top + 1 + game.rows // 2
    help_y = top + game.rows + 2  # the key line under the board
    if game.over:
        # Shown on the key line, not over the board, so the final board stays fully visible.
        title = " YOU WIN! " if game.won else " GAME OVER "
        put(stdscr, help_y, left, title, curses.A_REVERSE | curses.A_BOLD)
        put(stdscr, help_y, left + len(title), "   R: play again   Q: quit", curses.A_BOLD)
    else:
        if game.paused:
            msg = " PAUSED - P to resume "
            put(stdscr, mid_y, left + (board_w - len(msg)) // 2, msg, curses.A_REVERSE | curses.A_BOLD)
        put(stdscr, help_y, left, " Arrows: steer   P: pause   Q: quit", curses.A_DIM)
    stdscr.refresh()


def run(stdscr):
    if not curses.has_colors():
        return "This game needs a terminal that supports colour."
    curses.start_color()
    try:
        curses.use_default_colors()  # keep the terminal's own background for empty cells
    except curses.error:
        pass
    for kind, colour in CELL_COLOURS.items():
        curses.init_pair(kind, curses.COLOR_BLACK, colour)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)

    h, w = stdscr.getmaxyx()
    cols = min((w - 2) // CELL_W, MAX_COLS)
    rows = min(h - 4, MAX_ROWS)  # leave a status line above and a help line below
    if cols < MIN_COLS or rows < MIN_ROWS:
        return (
            f"Terminal too small: need at least {MIN_COLS * CELL_W + 2}x{MIN_ROWS + 4} "
            f"(columns x rows), have {w}x{h}."
        )

    game = Game(cols, rows)
    high = 0  # best score since the game was started; not saved between runs
    next_tick = time.monotonic() + game.delay

    while True:
        draw(stdscr, game, high)
        running = not game.over and not game.paused and fits(stdscr, game)

        if running:
            wait = next_tick - time.monotonic()
            if wait <= 0:
                game.step()
                if game.over:
                    high = max(high, game.score)
                next_tick = max(next_tick + game.delay, time.monotonic())
                continue
            stdscr.timeout(max(1, int(wait * 1000)))
        else:
            stdscr.timeout(-1)  # nothing moving: block until a key arrives

        key = stdscr.getch()
        if key == -1:
            continue
        if key in (ord("q"), ord("Q"), 27):
            return None
        if key in KEY_DIRS and running:
            game.turn(KEY_DIRS[key])
        elif game.over and key in (ord("r"), ord("R"), ord(" "), 10, 13, curses.KEY_ENTER):
            game.reset()
            next_tick = time.monotonic() + game.delay
        elif not game.over and key in (ord("p"), ord("P"), ord(" ")):
            game.paused = not game.paused
            next_tick = time.monotonic() + game.delay
        elif key == curses.KEY_RESIZE and not fits(stdscr, game):
            game.paused = True


def main():
    os.environ.setdefault("ESCDELAY", "25")  # make Esc respond quickly
    message = curses.wrapper(run)
    if message:
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
