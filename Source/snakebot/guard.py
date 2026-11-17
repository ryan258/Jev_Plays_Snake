"""The guard: decides which moves the AI is allowed to see, and how each one is described.

guard "off" is the fair test (no hints). The other modes add hints, so those runs
are "assisted"."""

import random

from .config import DEFAULT_GUARD
from .geometry import NAME_DIRS, adj, in_bounds
from .pathfinding import advance, bfs, clear_steps_ahead, flood_area, plan, tail_reachable
from .prompts import JEV_DESCRIPTIONS


def describe_move(s, snake, name, nxt, fallback_dir):
    """Work out how good one safe move is. Returns (text for the AI, open area, tail reachable?)."""
    d = NAME_DIRS[name]
    if snake is not None:
        after = advance(snake, nxt, s.food)
        tail_ok = tail_reachable(after, s.cols, s.rows)
        area = flood_area(nxt, set(after[1:]), s.cols, s.rows)
        if s.food is None:
            food_steps = None
        elif nxt == s.food:
            food_steps = 0
        else:
            path = bfs(nxt, s.food, set(after[:-1]), s.cols, s.rows)
            food_steps = len(path) if path is not None else None
    else:  # we lost track of the snake's order, so use rougher guesses
        area = flood_area(nxt, s.body - ({s.tail} if s.tail else set()), s.cols, s.rows)
        tail_ok = area >= len(s.body) + 1
        food_steps = (abs(nxt[0] - s.food[0]) + abs(nxt[1] - s.food[1])) if s.food else None

    tail_note = "tail reachable (safe loop)" if tail_ok else f"TRAP WARNING: tail unreachable (pocket {area} cells)"
    if food_steps == 0:
        food_note = "eats food immediately"
    elif food_steps is not None:
        food_note = f"shortest path to food {food_steps} steps"
    else:
        food_note = "no direct path to food (follow tail)"
    preferred = " [verifier preferred]" if fallback_dir == d else ""
    text = (f"{JEV_DESCRIPTIONS[name]} Target {nxt}: clear {clear_steps_ahead(s, d)} step(s) straight, "
            f"open area {area} cells ({tail_note}), {food_note}.{preferred}")
    return text, area, tail_ok


def analyze_candidates(s, tracker, since_food, guard=DEFAULT_GUARD):
    """Decide which moves to offer the AI, and how to describe each one.

    Returns (options, descriptions, fallback_dir):
      options       the move names to offer ("Up", "Down", ...), in random order
      descriptions  a sentence for each offered move
      fallback_dir  the path-finder's own best direction, used if the AI is too slow

    guard "off"    offer every move except the reversal, with plain descriptions
    guard "prompt" offer every move, but add warnings and hints to the descriptions
    guard "safe"   drop moves that hit a wall or the body right away
    guard "full"   also drop moves that trap the snake (its tail becomes unreachable)
    """
    heading = s.heading()
    non_reverse = [name for name, d in NAME_DIRS.items()
                   if heading is None or d != (-heading[0], -heading[1])]  # reversing does nothing
    if guard == "off":  # fair test: skip all the clever checks
        opts = list(non_reverse)
        random.shuffle(opts)
        return opts, {name: JEV_DESCRIPTIONS[name] for name in opts}, heading

    tracker.update(s)
    snake = tracker.snake

    # The path-finder's favourite move (our backup answer).
    restless = since_food > s.cols * s.rows * 2
    if snake is not None:
        best_cell = plan(snake, s.food, s.cols, s.rows, restless)
    else:
        free = [n for n in adj(s.head) if in_bounds(n, s.cols, s.rows) and (n not in s.body or n == s.tail)]
        best_cell = max(free, key=lambda n: flood_area(n, s.body, s.cols, s.rows), default=None)
    fallback_dir = (best_cell[0] - s.head[0], best_cell[1] - s.head[1]) if best_cell else heading

    safe_names, viable_names, areas, descriptions = [], [], {}, {}
    for name in non_reverse:
        d = NAME_DIRS[name]
        ahead = s.cell_ahead(d)
        nxt = (s.head[0] + d[0], s.head[1] + d[1])
        if ahead != "safe":
            descriptions[name] = f"{JEV_DESCRIPTIONS[name]} DANGER: hits {ahead} immediately at {nxt}."
            continue
        safe_names.append(name)
        descriptions[name], areas[name], tail_ok = describe_move(s, snake, name, nxt, fallback_dir)
        if tail_ok:
            viable_names.append(name)

    if guard == "prompt":
        opts = list(non_reverse)
    elif guard == "safe":
        opts = list(safe_names) or list(non_reverse)
    elif viable_names:  # guard == "full"
        opts = list(viable_names)
    elif safe_names:  # every safe move traps us: pick the one with the most room
        most = max(areas[n] for n in safe_names)
        opts = [n for n in safe_names if areas[n] == most]
    else:
        opts = list(non_reverse)

    random.shuffle(opts)
    return opts, {name: descriptions[name] for name in opts}, fallback_dir
