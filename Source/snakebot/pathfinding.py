"""Path-finding: ways to look ahead on the board.

Shortest paths, how much open room there is, and a simple plan for the next step.
The built-in algorithm player and the guard both use these."""

import random
from collections import deque

from .geometry import adj, in_bounds


class Tracker:
    """Remembers the snake's squares IN ORDER (head first).

    A photo shows the head, neck and tail, but not the order of the middle squares.
    So we follow the snake move by move. If we ever lose track, we work the order out
    from the snake's shape instead."""

    def __init__(self):
        self.snake = None

    def update(self, s):
        """Take in a new photo. Returns False if nothing moved."""
        cells = s.body | {s.head}
        old = self.snake
        if old:
            if s.head == old[0] and set(old) == cells:
                return False
            if abs(s.head[0] - old[0][0]) + abs(s.head[1] - old[0][1]) == 1:  # the head moved one square
                cand = [s.head] + old
                del cand[len(cells):]  # the old tail square is gone (unless the snake just ate)
                if set(cand) == cells:
                    self.snake = cand
                    return True
        self.snake = rebuild(s.head, cells)
        return True


def rebuild(head, cells, limit=20000):
    """Find an order for `cells` that is one connected path starting at `head` (or None)."""
    target = len(cells)
    path, visited = [head], {head}
    stack = [iter(ordered_next(head, cells, visited))]
    steps = 0
    while stack:
        if len(path) == target:
            return path
        steps += 1
        if steps > limit:  # give up rather than think forever
            return None
        nxt = next(stack[-1], None)
        if nxt is None:  # dead end: back up one square
            stack.pop()
            visited.discard(path.pop())
            continue
        path.append(nxt)
        visited.add(nxt)
        stack.append(iter(ordered_next(nxt, cells, visited)))
    return None


def ordered_next(p, cells, visited):
    # Try the square with the fewest unused neighbours first (it is the easiest to get stuck on).
    opts = [n for n in adj(p) if n in cells and n not in visited]
    return sorted(opts, key=lambda n: sum(1 for m in adj(n) if m in cells and m not in visited))


def bfs(start, goal, blocked, cols, rows):
    """Shortest walk from start to goal, not stepping on `blocked` squares.
    Returns the squares to step on (not including start), or None if there is no way."""
    prev = {start: None}  # where we came from, for each square we have visited
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
        random.shuffle(nbrs)  # break ties randomly so the bot doesn't get stuck in a rut
        for n in nbrs:
            if n not in prev and in_bounds(n, cols, rows) and n not in blocked:
                prev[n] = p
                q.append(n)
    return None


def flood_area(start, blocked, cols, rows):
    """How many free squares can be reached from start? (Like pouring water in and seeing how far it spreads.)"""
    seen, q = {start}, deque([start])
    while q:
        for n in adj(q.popleft()):
            if n not in seen and in_bounds(n, cols, rows) and n not in blocked:
                seen.add(n)
                q.append(n)
    return len(seen)


def advance(snake, cell, food):
    """The snake after its head steps into `cell`. It grows only if it eats."""
    return [cell] + (snake if cell == food else snake[:-1])


def tail_reachable(snake, cols, rows):
    """Can the head still find a way to its own tail? If so, the snake is not trapped."""
    if len(snake) < 2:
        return True
    return bfs(snake[0], snake[-1], set(snake[1:-1]), cols, rows) is not None


def plan(snake, food, cols, rows, restless):
    """Pick the next square for the head.

    1. Go straight for the food by the shortest path, but ONLY if the snake could still
       reach its own tail afterwards (so it can't trap itself).
    2. Otherwise chase the tail the long way round, to buy time.
    3. If even that fails, go where there is the most open space.
    `restless` means "we've circled too long without eating", so we shake things up randomly."""
    head = snake[0]
    blocked = set(snake[:-1])  # the tail moves out of the way this step

    if food is not None and not restless:
        path = bfs(head, food, blocked, cols, rows)
        if path:
            after = snake
            for cell in path:
                after = advance(after, cell, food)
            if tail_reachable(after, cols, rows):
                return path[0]

    moves = [n for n in adj(head) if in_bounds(n, cols, rows) and n not in blocked]
    if not moves:
        return None

    safe = []
    for n in moves:
        after = advance(snake, n, food)
        if tail_reachable(after, cols, rows):
            d = bfs(after[0], after[-1], set(after[1:-1]), cols, rows)
            safe.append((len(d) if d else 0, n))
    if safe:
        if restless:
            return random.choice(safe)[1]
        return max(safe)[1]  # the move with the longest route back to the tail = the most room

    return max(moves, key=lambda n: flood_area(n, set(advance(snake, n, food)[1:]), cols, rows))


def clear_steps_ahead(s, d, max_steps=10):
    """How many squares can the head go straight in direction d before hitting something?"""
    steps = 0
    x, y = s.head
    for _ in range(max_steps):
        x, y = x + d[0], y + d[1]
        if not in_bounds((x, y), s.cols, s.rows):
            break
        if (x, y) in s.body and (x, y) != s.tail:
            break
        steps += 1
    return steps
