"""Directions and neighbours on the board.

The board is a grid. x grows to the right and y grows DOWN the screen.
This module imports nothing else from the bot."""


# ---- Directions (x grows to the right, y grows DOWN the screen) -------------------
UP, DOWN, LEFT, RIGHT = (0, -1), (0, 1), (-1, 0), (1, 0)

DIRS = (UP, DOWN, LEFT, RIGHT)

KEY_NAMES = {UP: "Up", DOWN: "Down", LEFT: "Left", RIGHT: "Right"}

NAME_DIRS = {v: k for k, v in KEY_NAMES.items()}


def adj(p):
    """The four squares touching p."""
    return [(p[0] + dx, p[1] + dy) for dx, dy in DIRS]


def in_bounds(p, cols, rows):
    return 0 <= p[0] < cols and 0 <= p[1] < rows
