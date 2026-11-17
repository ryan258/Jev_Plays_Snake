#!/usr/bin/env python3
"""Terminal Snake (version 1.1), drawn with solid blocks of colour. Steer with the arrow keys.

Influenced by an earlier project: typesafe-snake by sorrycc
(github.com/sorrycc/typesafe-snake). No code was copied from it.

Keys:
    Arrow keys   steer
    P / Space    pause / resume
    R / Enter    play again after the game ends
    Q / Esc      quit

Colours (the bot reads the board by these colours, so don't change them casually):
yellow = head, cyan = neck (the square behind the head), green = body,
blue = tail, red = food, magenta = head after a crash.
"""

import curses  # a built-in tool for drawing on the terminal screen
import os
import random
import sys
import time
from collections import deque
from curses.textpad import rectangle

VERSION = "1.1"

# ---- Settings you can change ----
MAX_COLS, MAX_ROWS = 40, 20  # the biggest board allowed (squares across, squares down)
MIN_COLS, MIN_ROWS = 12, 6   # the smallest board that is still fun
START_LENGTH = 4             # how long the snake is at the start
START_DELAY = 0.3            # seconds between steps
SPEEDUP = 1.0                # each food multiplies the delay by this (1.0 = same speed forever)

# Each square is two characters wide. Letters are about twice as tall as they are wide,
# so two characters make the square look like a square.
CELL_W = 2

# A direction is (across, down). Down the screen means the number gets BIGGER.
UP, DOWN, LEFT, RIGHT = (0, -1), (0, 1), (-1, 0), (1, 0)
KEY_DIRS = {
    curses.KEY_UP: UP,
    curses.KEY_DOWN: DOWN,
    curses.KEY_LEFT: LEFT,
    curses.KEY_RIGHT: RIGHT,
}

# Each kind of square gets a "colour pair" number. The head, neck and tail get their own
# colours so one look at the screen shows which way the snake faces and where it ends.
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
    """The rules of snake. It knows nothing about the screen: it only keeps track of the snake."""

    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.reset()

    def reset(self):
        """Start a fresh game."""
        cx, cy = self.cols // 2, self.rows // 2
        self.snake = deque((cx - i, cy) for i in range(START_LENGTH))  # the first square is the head
        self.occupied = set(self.snake)  # a quick way to ask "is this square part of the snake?"
        self.direction = RIGHT
        self.pending = deque()  # turns waiting their turn, so quick taps aren't lost
        self.score = 0
        self.delay = START_DELAY
        self.over = False
        self.won = False
        self.paused = False
        self.food = self._place_food()

    def _place_food(self):
        """Put the food on a random empty square. None means the board is full."""
        free = [(x, y) for x in range(self.cols) for y in range(self.rows) if (x, y) not in self.occupied]
        return random.choice(free) if free else None

    def turn(self, d):
        """Line up a turn. Turning the same way, or straight back into the neck, does nothing."""
        last = self.pending[-1] if self.pending else self.direction
        if d == last or (d[0] == -last[0] and d[1] == -last[1]):
            return
        if len(self.pending) < 2:  # remember at most two turns
            self.pending.append(d)

    def step(self):
        """Move the snake one square."""
        if self.pending:
            self.direction = self.pending.popleft()
        hx, hy = self.snake[0]
        dx, dy = self.direction
        new = (hx + dx, hy + dy)

        if not (0 <= new[0] < self.cols and 0 <= new[1] < self.rows):  # hit a wall
            self.over = True
            return

        grows = new == self.food
        tail = self.snake[-1]
        # The tail slides away as the head arrives, so stepping onto it is allowed (unless we just ate).
        if new in self.occupied and not (new == tail and not grows):  # hit our own body
            self.over = True
            return

        if not grows:
            self.occupied.discard(self.snake.pop())  # the tail moves forward, so drop the last square
        self.snake.appendleft(new)
        self.occupied.add(new)

        if grows:
            self.score += 1
            self.delay *= SPEEDUP
            self.food = self._place_food()
            if self.food is None:  # no empty squares left: the snake filled the board!
                self.over = self.won = True


def fits(stdscr, game):
    """Is the terminal big enough to draw the board?"""
    h, w = stdscr.getmaxyx()
    return h >= game.rows + 4 and w >= game.cols * CELL_W + 2


def put(stdscr, y, x, text, attr=0):
    """Write text at a spot on the screen, never past the edge (writing off-screen causes an error)."""
    h, w = stdscr.getmaxyx()
    if 0 <= y < h and 0 <= x < w - 1:
        try:
            stdscr.addnstr(y, x, text, w - 1 - x, attr)
        except curses.error:
            pass


def draw(stdscr, game, high):
    """Draw everything: the score line, the board, the snake, the food and the help line."""
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    if not fits(stdscr, game):
        put(stdscr, 0, 0, "Terminal too small - please enlarge it (Q to quit)")
        stdscr.refresh()
        return

    board_w = game.cols * CELL_W + 2
    left = (w - board_w) // 2  # centre the board
    top = 1

    status = f" Score: {game.score}   High: {max(high, game.score)}   Length: {len(game.snake)}"
    put(stdscr, 0, left, status, curses.A_BOLD)
    rectangle(stdscr, top, left, top + game.rows + 1, left + board_w - 1)

    def cell(pos, kind):
        """Paint one square of the board in a colour."""
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
    help_y = top + game.rows + 2  # the line under the board
    if game.over:
        # The message goes on the help line, not on the board, so you can still see the final board.
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
    """The game loop. Returns None for a normal quit, or a message if something is wrong."""
    if not curses.has_colors():
        return "This game needs a terminal that supports colour."
    curses.start_color()
    try:
        curses.use_default_colors()  # keep the terminal's own background for empty squares
    except curses.error:
        pass
    for kind, colour in CELL_COLOURS.items():
        curses.init_pair(kind, curses.COLOR_BLACK, colour)
    try:
        curses.curs_set(0)  # hide the blinking cursor
    except curses.error:
        pass
    stdscr.keypad(True)  # make arrow keys arrive as one key each

    h, w = stdscr.getmaxyx()
    cols = min((w - 2) // CELL_W, MAX_COLS)
    rows = min(h - 4, MAX_ROWS)  # leave a score line above and a help line below
    if cols < MIN_COLS or rows < MIN_ROWS:
        return (
            f"Terminal too small: need at least {MIN_COLS * CELL_W + 2}x{MIN_ROWS + 4} "
            f"(columns x rows), have {w}x{h}."
        )

    game = Game(cols, rows)
    high = 0  # best score since the game started (not saved when you quit)
    next_tick = time.monotonic() + game.delay  # when the snake should step next

    while True:
        draw(stdscr, game, high)
        running = not game.over and not game.paused and fits(stdscr, game)

        if running:
            wait = next_tick - time.monotonic()
            if wait <= 0:  # time for a step
                game.step()
                if game.over:
                    high = max(high, game.score)
                next_tick = max(next_tick + game.delay, time.monotonic())
                continue
            stdscr.timeout(max(1, int(wait * 1000)))  # wait for a key, but only until the next step
        else:
            stdscr.timeout(-1)  # nothing is moving, so wait for a key as long as it takes

        key = stdscr.getch()
        if key == -1:  # no key before the timeout
            continue
        if key in (ord("q"), ord("Q"), 27):  # 27 is the Esc key
            return None
        if key in KEY_DIRS and running:
            game.turn(KEY_DIRS[key])
        elif game.over and key in (ord("r"), ord("R"), ord(" "), 10, 13, curses.KEY_ENTER):
            game.reset()
            next_tick = time.monotonic() + game.delay
        elif not game.over and key in (ord("p"), ord("P"), ord(" ")):
            game.paused = not game.paused
            next_tick = time.monotonic() + game.delay
        elif key == curses.KEY_RESIZE and not fits(stdscr, game):  # the window got too small: pause
            game.paused = True


def main():
    os.environ.setdefault("ESCDELAY", "25")  # make the Esc key react quickly
    message = curses.wrapper(run)  # wrapper sets up the screen, and puts the terminal back when we finish
    if message:
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
