"""Reading the game screen.

The game paints every square with a colour. This module turns a photo of the
screen into a Screen: where the head, neck, body, tail and food are."""

import re

from .config import START_LENGTH
from .geometry import KEY_NAMES, adj

CELL_W = 2  # the game draws each square of the board two characters wide

# The game paints each square with a background colour. These are the standard terminal
# colour numbers. The bot reads the board by looking at those colours.
RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN = 1, 2, 3, 4, 5, 6

FOOD, BODY, HEAD, TAIL, NECK, DEAD = RED, GREEN, YELLOW, BLUE, CYAN, MAGENTA  # DEAD = head after a crash

SGR = re.compile(r"\x1b\[([0-9;]*)m")  # a terminal "change the colours now" code


def new_style():
    return {"fg": None, "bg": None, "bold": False, "dim": False, "rev": False}


def sgr_style(params, st):
    """Update a text style (colours, bold, ...) from one colour code like "1;43"."""
    codes = [int(p) if p else 0 for p in params.split(";")]
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0:
            st = new_style()
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
        elif c in (38, 48) and i + 2 < len(codes) and codes[i + 1] == 5:  # 256-colour form
            n = codes[i + 2]
            st["fg" if c == 38 else "bg"] = n if n < 16 else None
            i += 2
        elif c in (38, 48) and i + 1 < len(codes) and codes[i + 1] == 2:  # 24-bit colour: the game never uses it
            i += 4
        i += 1
    return st


def decode(text):
    """Split a captured screen into two grids: the letters, and each spot's background colour.
    Returns (chars, colours); colours[row][col] is a colour number, or None for "no colour"."""
    chars, colours = [], []
    style = new_style()
    for line in text.split("\n"):
        row_chars, row_bg = [], []
        pos = 0
        for m in SGR.finditer(line + "\x1b[m"):  # the extra code flushes the end of the line
            for ch in line[pos:m.start()]:
                row_chars.append(ch)
                row_bg.append(style["bg"])
            pos = m.end()
            style = sgr_style(m.group(1), style)
        chars.append("".join(row_chars))
        colours.append(row_bg)
    return chars, colours


class Screen:
    """Everything the bot can see in one photo of the game."""

    def __init__(self):
        self.cols = self.rows = 0
        self.head = self.neck = self.tail = self.food = None
        self.body = set()  # every snake square EXCEPT the head (the neck and tail are in here too)
        self.score = 0
        self.over = self.paused = False

    def frame_id(self):
        """A fingerprint of the board. A new fingerprint means the snake moved."""
        return (self.head, self.neck, self.tail, self.food, len(self.body))

    def complete(self):
        """Is the whole snake drawn properly? A photo taken while the game is still redrawing
        can miss squares or show old colours. We skip those photos.

        Checks: head, neck and tail all exist; the length is START_LENGTH + score; the neck
        touches the head; and the snake is ONE connected chain."""
        if self.head is None or self.neck is None or self.tail is None:
            return False
        if len(self.body) + 1 != START_LENGTH + self.score:
            return False
        if self.neck not in adj(self.head):
            return False
        seen, todo = {self.head}, [self.head]  # walk along the snake, starting at the head
        while todo:
            for n in adj(todo.pop()):
                if n in self.body and n not in seen:
                    seen.add(n)
                    todo.append(n)
        return len(seen) == len(self.body) + 1

    def cell_ahead(self, d):
        """What is in the square the head would step into? "wall", "body" or "safe".
        The tail counts as safe because it moves away as the head arrives."""
        x, y = self.head[0] + d[0], self.head[1] + d[1]
        if not (0 <= x < self.cols and 0 <= y < self.rows):
            return "wall"
        return "body" if (x, y) in self.body and (x, y) != self.tail else "safe"

    def crash_cause(self, pressed=None):
        """Use the game-over photo to work out what the snake hit.
        Returns (cause, key_late). cause is "wall", "body" or "unknown".
        key_late is True if a safe turn was pressed but arrived too late.
        `pressed` is the direction of the key the bot pressed on this board, if any."""
        heading = self.heading()
        if not self.head or not heading:
            return "unknown", False
        if pressed and pressed != heading:
            turned = self.cell_ahead(pressed)
            if turned != "safe":
                return turned, False  # the turn happened, and it was the crash
            straight = self.cell_ahead(heading)
            return (straight if straight != "safe" else "unknown"), True
        straight = self.cell_ahead(heading)
        return (straight if straight != "safe" else "unknown"), False

    def heading(self):
        """Which way the snake is facing: from the neck to the head."""
        if self.head and self.neck:
            return (self.head[0] - self.neck[0], self.head[1] - self.neck[1])
        return None

    def grid_text(self, compact=False):
        """Draw the board as letters for the AI: H head, N neck, B body, T tail, F food, . empty."""
        grid = [["."] * self.cols for _ in range(self.rows)]
        for x, y in self.body:
            grid[y][x] = "B"
        # Later letters overwrite earlier ones, so the head wins any tie.
        for cell, letter in ((self.tail, "T"), (self.neck, "N"), (self.food, "F"), (self.head, "H")):
            if cell:
                grid[cell[1]][cell[0]] = letter
        if compact:  # no spaces, plus a header line with the key facts (about 45% fewer tokens)
            header = (f"Head={self.head} Neck={self.neck} Tail={self.tail} "
                      f"Food={self.food} Heading={KEY_NAMES.get(self.heading(), 'None')} "
                      f"Len={len(self.body) + 1}")
            return header + "\n" + "\n".join("".join(row) for row in grid)
        return "\n".join(" ".join(row) for row in grid)


def read_screen(text):
    """Turn a captured screen into a Screen. Returns None if no game board is showing."""
    chars, colours = decode(text)

    # Find the board's frame: the top-left corner, then top-right and bottom-left.
    top = next((r for r, line in enumerate(chars) if "┌" in line), None)
    if top is None:
        return None
    left = chars[top].index("┌")
    right = chars[top].find("┐", left)
    bottom = next((r for r in range(top + 1, len(chars)) if chars[r][left:left + 1] == "└"), None)
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
            if colour in (HEAD, DEAD):
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
