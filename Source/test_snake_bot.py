"""Offline tests for snake_bot.py: no tmux, network or API key needed.

Run from this directory:  python3 -m unittest -v test_snake_bot
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snakebot import config as cfg
from snakebot import env as envmod
from snakebot import geometry as geo
from snakebot import guard as guard_mod
from snakebot import launcher
from snakebot import pathfinding as pf
from snakebot import screen as scr
from snakebot.players import jev as jevmod
from snakebot.players import wire

# SGR background code per colour the game paints (40 + colour number).
PAINT = {"head": scr.HEAD, "neck": scr.NECK, "body": scr.BODY, "tail": scr.TAIL, "food": scr.FOOD}


def render(cols, rows, snake, food=None, score=0, extra=""):
    """A captured-screen string like the game's: a box of 2-column coloured cells, head first."""
    paint = {}
    for i, cell in enumerate(snake):
        kind = "head" if i == 0 else "neck" if i == 1 else "tail" if i == len(snake) - 1 else "body"
        paint[cell] = kind
    if food:
        paint[food] = "food"
    lines = ["┌" + "─" * (cols * 2) + "┐"]
    for y in range(rows):
        row = ""
        for x in range(cols):
            kind = paint.get((x, y))
            row += f"\x1b[{40 + PAINT[kind]}m  \x1b[0m" if kind else "  "
        lines.append("│" + row + "│")
    lines.append("└" + "─" * (cols * 2) + "┘")
    lines.append(f"Score: {score} {extra}")
    return "\n".join(lines)


def line_snake(length=cfg.START_LENGTH, y=2, head_x=None):
    """A straight snake heading right, head first."""
    head_x = length if head_x is None else head_x
    return [(head_x - i, y) for i in range(length)]


class ReadScreenTests(unittest.TestCase):
    def test_reads_every_cell_type(self):
        snake = line_snake()
        s = scr.read_screen(render(12, 6, snake, food=(8, 4)))
        self.assertEqual((s.cols, s.rows), (12, 6))
        self.assertEqual(s.head, snake[0])
        self.assertEqual(s.neck, snake[1])
        self.assertEqual(s.tail, snake[-1])
        self.assertEqual(s.food, (8, 4))
        self.assertEqual(s.heading(), geo.RIGHT)
        self.assertEqual(len(s.body) + 1, len(snake))
        self.assertTrue(s.complete())

    def test_no_board_means_none(self):
        self.assertIsNone(scr.read_screen("nothing to see here"))

    def test_game_over_and_pause_flags(self):
        snake = line_snake()
        self.assertTrue(scr.read_screen(render(12, 6, snake, extra="GAME OVER")).over)
        self.assertTrue(scr.read_screen(render(12, 6, snake, extra="PAUSED")).paused)

    def test_wrong_length_is_a_mid_redraw_read(self):
        s = scr.read_screen(render(12, 6, line_snake(), score=1))  # length should be START+1
        self.assertFalse(s.complete())

    def test_missing_neck_is_incomplete(self):
        s = scr.read_screen(render(12, 6, line_snake()))
        s.neck = None
        self.assertFalse(s.complete())

    def test_cell_ahead(self):
        s = scr.Screen()
        s.cols = s.rows = 5
        s.head, s.neck, s.tail = (0, 0), (1, 0), (2, 0)
        s.body = {(1, 0), (2, 0)}
        self.assertEqual(s.cell_ahead(geo.UP), "wall")
        self.assertEqual(s.cell_ahead(geo.LEFT), "wall")
        self.assertEqual(s.cell_ahead(geo.RIGHT), "body")
        self.assertEqual(s.cell_ahead(geo.DOWN), "safe")


class TrackerTests(unittest.TestCase):
    def test_rebuild_orders_a_bent_snake_from_the_head(self):
        cells = {(0, 0), (1, 0), (2, 0), (2, 1)}
        self.assertEqual(pf.rebuild((2, 1), cells), [(2, 1), (2, 0), (1, 0), (0, 0)])

    def test_tracker_follows_a_move(self):
        t = pf.Tracker()
        s1 = scr.read_screen(render(12, 6, line_snake()))
        t.update(s1)
        moved = [(c[0] + 1, c[1]) for c in line_snake()]
        s2 = scr.read_screen(render(12, 6, moved))
        self.assertTrue(t.update(s2))
        self.assertEqual(t.snake, moved)
        self.assertFalse(t.update(s2))  # same frame again: nothing moved


class PlannerTests(unittest.TestCase):
    def test_heads_for_the_food(self):
        snake = [(3, 2), (2, 2), (1, 2), (0, 2)]
        self.assertEqual(pf.plan(snake, (6, 2), 10, 5, restless=False), (4, 2))

    def test_never_moves_into_a_wall_or_the_body(self):
        snake = [(5, 0), (4, 0), (3, 0), (2, 0)]  # on the top edge, heading right
        for food in (None, (5, 4), (0, 0)):
            nxt = pf.plan(snake, food, 10, 5, restless=False)
            self.assertTrue(0 <= nxt[0] < 10 and 0 <= nxt[1] < 5, nxt)
            self.assertNotIn(nxt, snake[:-1])

    def test_no_move_when_boxed_in(self):
        # Head in a corner of a 2x3 board, both its neighbours are body: nowhere to go.
        snake = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 2)]
        self.assertIsNone(pf.plan(snake, None, 2, 3, restless=False))


class GuardTests(unittest.TestCase):
    def setUp(self):
        # Snake along the top edge heading right: Up is a wall, Left is the reversal.
        self.s = scr.read_screen(render(12, 6, [(5, 0), (4, 0), (3, 0), (2, 0)], food=(9, 4)))

    def options(self, guard):
        return set(guard_mod.analyze_candidates(self.s, pf.Tracker(), 0, guard=guard)[0])

    def test_off_offers_every_non_reversal_move(self):
        self.assertEqual(self.options("off"), {"Up", "Down", "Right"})

    def test_off_skips_the_verifier(self):
        with mock.patch.object(guard_mod, "plan", side_effect=AssertionError("verifier ran")):
            self.options("off")

    def test_prompt_keeps_every_move_but_flags_the_wall(self):
        opts, descriptions, _fallback = guard_mod.analyze_candidates(self.s, pf.Tracker(), 0, guard="prompt")
        self.assertEqual(set(opts), {"Up", "Down", "Right"})
        self.assertIn("DANGER", descriptions["Up"])

    def test_safe_and_full_drop_the_wall_move(self):
        self.assertEqual(self.options("safe"), {"Down", "Right"})
        self.assertEqual(self.options("full"), {"Down", "Right"})


class DotenvTests(unittest.TestCase):
    def load(self, content):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"
            path.write_text(content)
            with mock.patch.dict(os.environ, {}, clear=False):
                for k in ("T_PLAIN", "T_QUOTED", "T_HASH", "T_INLINE", "T_EXPORT", "T_SET"):
                    os.environ.pop(k, None)
                os.environ["T_SET"] = "keep"
                envmod.load_dotenv(path)
                return {k: os.environ.get(k) for k in
                        ("T_PLAIN", "T_QUOTED", "T_HASH", "T_INLINE", "T_EXPORT", "T_SET")}

    def test_parsing(self):
        got = self.load("# comment\nT_PLAIN=abc\nT_QUOTED=\"a # b\"\nT_HASH=ab#cd\n"
                        "T_INLINE=xyz # note\nexport T_EXPORT=1\nT_SET=overwritten\n")
        self.assertEqual(got["T_PLAIN"], "abc")
        self.assertEqual(got["T_QUOTED"], "a # b")
        self.assertEqual(got["T_HASH"], "ab#cd")  # a "#" inside a value is not a comment
        self.assertEqual(got["T_INLINE"], "xyz")
        self.assertEqual(got["T_EXPORT"], "1")
        self.assertEqual(got["T_SET"], "keep")  # already-set variables win


class ReplyParsingTests(unittest.TestCase):
    OPTS = ["Up", "Down", "Right"]

    @staticmethod
    def chat(content, **usage):
        return {"choices": [{"message": {"content": content}}], "usage": usage}

    def test_chat_json_reply(self):
        ans, tokens, cost = wire.parse_chat(self.chat('{"plan": "go down", "move": "down"}',
                                                    prompt_tokens=100, cost=0.5), self.OPTS)
        self.assertEqual(ans["choice"], "Down")
        self.assertEqual(ans["plan"], "go down")
        self.assertEqual((tokens, cost), (100, 0.5))

    def test_chat_code_fenced_json(self):
        ans, _, _ = wire.parse_chat(self.chat('```json\n{"move": "Right"}\n```'), self.OPTS)
        self.assertEqual(ans["choice"], "Right")

    def test_chat_prose_naming_one_direction(self):
        ans, _, _ = wire.parse_chat(self.chat("I would go Right."), self.OPTS)
        self.assertEqual(ans["choice"], "Right")

    def test_chat_prose_naming_two_directions_is_rejected(self):
        with self.assertRaises(ValueError):
            wire.parse_chat(self.chat("Up looks bad, so Down."), self.OPTS)

    def test_chat_json_with_a_bad_move_does_not_fall_back_to_the_plan_text(self):
        with self.assertRaises(ValueError):
            wire.parse_chat(self.chat('{"plan": "go Right", "move": "Left"}'), self.OPTS)

    def test_chat_move_outside_the_offered_options_is_rejected(self):
        with self.assertRaises(ValueError):
            wire.parse_chat(self.chat('{"move": "Left"}'), self.OPTS)

    def test_systemone_reply(self):
        payload = {"answers": {"move": {"choice": "Up", "confidence": 0.8,
                                        "probabilities": {"Up": 0.8}}},
                   "usage": {"input_tokens": 1000}}
        ans, tokens, cost = wire.parse_systemone(payload, ["Up", "Down"])
        self.assertEqual((ans["choice"], tokens), ("Up", 1000))
        self.assertAlmostEqual(cost, 1000 * cfg.PRICE_PER_TOKEN)

    def test_systemone_rejects_an_unoffered_choice_and_a_missing_answer(self):
        payload = {"answers": {"move": {"choice": "Left", "confidence": 1}}}
        with self.assertRaises(ValueError):
            wire.parse_systemone(payload, ["Up", "Down"])
        with self.assertRaises(KeyError):
            wire.parse_systemone({}, ["Up"])


class PlayerFlowTests(unittest.TestCase):
    """The shared request flow, with the network call stubbed out."""

    def make(self, guard="off"):
        env = {"TYPESAFE_API_KEY": "test-key"}
        with mock.patch.dict(os.environ, env):
            return jevmod.JevPlayer("unused.txt", "jev-latest", guard=guard)

    def frame(self):
        return scr.read_screen(render(12, 6, [(5, 2), (4, 2), (3, 2), (2, 2)], food=(9, 2)))

    def test_good_answer_returns_a_direction_and_resets_the_error_count(self):
        p = self.make()
        p.errors_in_a_row = 3
        reply = {"answers": {"move": {"choice": "Right", "confidence": 0.9}},
                 "usage": {"input_tokens": 50}, "model": "jev-test"}
        with mock.patch.object(p, "post", return_value=(200, reply)):
            d, info = p.choose(self.frame())
        self.assertEqual(d, geo.RIGHT)
        self.assertEqual(p.errors_in_a_row, 0)
        self.assertEqual(info["input_tokens"], 50)

    def test_ten_failures_in_a_row_stop_the_run(self):
        p = self.make()
        with mock.patch.object(p, "post", return_value=(500, {"detail": "boom"})):
            for _ in range(cfg.MAX_ERRORS_IN_A_ROW):
                d, info = p.choose(self.frame())
                self.assertIsNone(d)
                self.assertIn("error", info)
        self.assertIn("failed 10 calls in a row", p.stop)

    def test_bad_key_and_no_credits_stop_at_once(self):
        for status, words in ((401, "rejected the API key"), (402, "out of API credits")):
            p = self.make()
            with mock.patch.object(p, "post", return_value=(status, {"detail": "x"})):
                p.choose(self.frame())
            self.assertIn(words, p.stop)

    def test_network_error_is_counted_not_raised(self):
        p = self.make()
        with mock.patch.object(p, "post", side_effect=OSError("down")):
            d, info = p.choose(self.frame())
        self.assertIsNone(d)
        self.assertEqual(p.errors_in_a_row, 1)
        self.assertIn("OSError", info["error"])


class LauncherTests(unittest.TestCase):
    def test_small_terminals_are_refused_and_big_ones_pass(self):
        self.assertIsNone(launcher.size_problem(cfg.MIN_TERMINAL_COLS, cfg.MIN_TERMINAL_ROWS))
        self.assertIsNone(launcher.size_problem(200, 60))
        for cols, rows in ((74, 8), (cfg.MIN_TERMINAL_COLS - 1, 60), (200, cfg.MIN_TERMINAL_ROWS - 1)):
            message = launcher.size_problem(cols, rows)
            self.assertIn(f"{cols} x {rows}", message)


if __name__ == "__main__":
    unittest.main()
