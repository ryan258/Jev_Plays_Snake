"""The algorithm player: a path-finder with no AI and no internet."""

from ..geometry import adj, in_bounds
from ..pathfinding import Tracker, flood_area, plan


class AlgorithmPlayer:
    """The built-in path-finder. No internet, no AI. It uses plan() to pick every move."""

    def __init__(self):
        self.last = ""
        self.new_game()

    def new_game(self):
        self.tracker = Tracker()
        self.since_food = 0
        self.last_score = 0

    def choose(self, s, step_budget=None):
        self.tracker.update(s)
        self.since_food = 0 if s.score > self.last_score else self.since_food + 1
        self.last_score = s.score
        snake = self.tracker.snake
        if snake is None:  # lost track of the order: just head for the roomiest free square
            free = [n for n in adj(s.head) if in_bounds(n, s.cols, s.rows) and n not in s.body]
            nxt = max(free, key=lambda n: flood_area(n, s.body, s.cols, s.rows), default=None)
        else:
            nxt = plan(snake, s.food, s.cols, s.rows, self.since_food > s.cols * s.rows * 2)
        info = {"board": s.grid_text()}
        if nxt is None:
            return None, info
        return (nxt[0] - s.head[0], nxt[1] - s.head[1]), info

    def close(self):
        pass
