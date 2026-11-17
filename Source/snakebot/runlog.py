"""The run log: writes everything that happens to a .jsonl file (for programs)
and a .txt file (for people), plus the settings record at the start."""

import json
import os
import sys
import time
from pathlib import Path

from .config import (
    DEFAULT_OPENROUTER_CHAT_URL,
    DEFAULT_OPENROUTER_JEV_URL,
    JEV_HOST,
    JEV_PATH,
    KEY_MARGIN,
    POLL_NEW_FRAME,
    PRICE_PER_TOKEN,
    REQUEST_TIMEOUT,
    VERSION,
)
from .players.models import is_jev_model
from .prompts import JEV_DESCRIPTIONS, JEV_INSTRUCTIONS
from .tmuxio import tmux


class Log:
    """Writes every event to a .jsonl file (one JSON record per line, for programs)
    and the same events to a .txt file with the same name (for people to read).

    Record types: session_start, move, game_end, session_end.
    The README lists what each one holds."""

    def __init__(self, path):
        self.path = path
        self.f = self.text = None
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.f = open(path, "a")
            text_path = Path(path).with_suffix(".txt")
            if text_path == Path(path):  # the log is already a .txt file, so use another name
                text_path = Path(path).with_name(Path(path).stem + "_readable.txt")
            self.text_path = text_path
            self.text = TextLog(open(text_path, "a"))

    def write(self, kind, **fields):
        if self.f:
            rec = {"type": kind, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), **fields}
            self.f.write(json.dumps(rec) + "\n")
            self.f.flush()  # save right away, so a crash can't lose it
            try:
                self.text.write(rec)
            except Exception as e:  # noqa: BLE001 - a problem in the readable log must never stop the bot
                self.text.out(f"(could not write this {kind} record as text: {e})")

    def close(self):
        if self.f:
            self.f.close()
            self.text.f.close()


# Columns of the move table in the text log: (title, width). Titles and values are padded to the same width.
JEV_COLUMNS = [("Time", 8), ("Move", 4), ("Score", 5), ("Offered", 18), ("Jev Chose", 9),
               ("Conf", 4), ("Up", 4), ("Down", 4), ("Left", 4), ("Right", 5), ("Reply", 7),
               ("Key Pressed", 0)]

ALGO_COLUMNS = [("Time", 8), ("Move", 4), ("Score", 5), ("Key Pressed", 0)]

ENDINGS = {"wall": "hit the wall", "body": "hit its body", "won": "won (board full)", "unknown": "cause unknown"}

RULE = "=" * 100


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


class TextLog:
    """Turns log records into plain English: a header, one line per move,
    a summary for each game, and a summary for the whole run."""

    def __init__(self, f):
        self.f = f
        self.game = None     # the game number we are printing moves for
        self.model = None    # the model's full name (only known after the first answer)
        self.is_jev = False  # an AI player (True) or the algorithm (False)

    def out(self, line=""):
        self.f.write(line + "\n")
        self.f.flush()

    def write(self, r):
        getattr(self, r["type"])(r)  # call session_start, move, game_end or session_end

    def session_start(self, r):
        g, bot, jev, env = r.get("game", {}), r.get("bot", {}), r.get("jev"), r.get("environment", {})
        self.is_jev = bot.get("player") in ("jev", "openrouter")
        self.out(RULE)
        self.out(f"Snake bot log    snake_bot.py {r.get('snake_bot_version')}    "
                 f"snake.py {r.get('snake_version')}    started {r['time'].replace('T', ' ')}")
        self.out(RULE)
        provider = "OpenRouter" if bot.get("player") == "openrouter" else "Jev"
        player = (f"{provider} (model requested: {jev.get('model_requested')}, guard: {bot.get('guard')})"
                  if self.is_jev and jev else "built-in algorithm")
        if self.is_jev and bot.get("assisted"):
            player += "  [ASSISTED: lookahead hints / move filtering, not a raw-board run]"
        self.out(f"Player:   {player}")
        self.out(f"Board:    {g.get('board_cols_seen')} x {g.get('board_rows_seen')}, "
                 f"snake starts {g.get('start_length')} long, "
                 f"{g.get('seconds_per_move_at_start')} s per move ({g.get('speed_note')})")
        self.out(f"Games:    {bot.get('games_requested')}")
        if self.is_jev and jev:
            self.out(f"Offered:  {bot.get('moves_offered')}")
            self.out(f"Late:     {bot.get('late_answer_rule')}")
            self.out(f"Price:    ${jev.get('price_usd_per_million_input_tokens')} per million input tokens")
        else:
            self.out(f"Strategy: {bot.get('strategy')}")
        self.out(f"Software: Python {env.get('python')}, {env.get('tmux')}")
        if self.is_jev and jev:
            self.out(f"\nInstructions sent to {provider} with every board:")
            line = "   "
            for word in jev.get("instructions", "").split():  # wrap long text to fit an editor window
                if len(line) + len(word) > 96:
                    self.out(line)
                    line = "   "
                line += " " + word
            self.out(line)
            self.out("\nMove lines: Offered is the order the moves were sent in; Conf is the model's "
                     "confidence; Up Down Left Right")
            self.out("are the probability for each move (- = not offered); Reply is the response time.")
            self.out("\nBase option descriptions:")
            for k, v in jev.get("option_descriptions", {}).items():
                self.out(f"    {k:<6} {v}")

    def move(self, r):
        answered = r.get("model") and not r.get("forced")
        if self.model is None and answered:  # the model's full name arrives with its first answer
            self.model = r["model"]
            self.out(f"\nModel answering: {self.model}")
        if r.get("game") != self.game:  # a new game starts: print its table headings
            self.game = r.get("game")
            self.out(f"\nGame {self.game}")
            columns = JEV_COLUMNS if self.is_jev else ALGO_COLUMNS
            self.row(columns, [name for name, _ in columns])
        if answered and r["model"] != self.model:
            self.model = r["model"]
            self.out(f"  (AI model changed to: {self.model})")
        if r.get("previous_key_landed_late"):
            self.out("  (the key pressed on the move above reached the game a step late)")
        clock = r["time"][11:]
        key = r.get("key_pressed") or "none, keeps going straight"
        if not self.is_jev:
            self.row(ALGO_COLUMNS, [clock, r.get("move"), r.get("score"), key])
            return
        offered = " ".join(r.get("options", []))
        start = [clock, r.get("move"), r.get("score"), offered]
        if "error" in r:
            tail = (f"API timeout/error -> local guard pressed {key}" if r.get("fallback_used")
                    else "no answer: " + r["error"][:60])
            self.row(JEV_COLUMNS[:4], start, tail=tail)
            return
        ans = r.get("answer", {})
        probs = ans.get("probabilities", {})
        cells = [f"{probs[m]:.2f}" if m in probs else "-" for m in ("Up", "Down", "Left", "Right")]  # "-" = not offered
        if r.get("late"):
            why = {"snake moved": "snake already moved",
                   "too close": "too close to next move"}.get(r.get("late_reason"), "too late")
            key = f"none: late ({why}), dropped"
        elif not r.get("key_pressed"):
            key = f"none, already going {ans.get('choice', 'that way')}"
        elif r.get("forced"):
            key = f"{key} (forced safe move, 0 ms)"
        if ans.get("plan"):
            key = f"{key}  [plan: {ans['plan']}]"
        self.row(JEV_COLUMNS, [*start, ans.get("choice", "?"), f"{ans.get('confidence', 0):.2f}", *cells,
                               f"{r.get('response_ms', 0):.0f} ms", key])

    def row(self, columns, values, tail=""):
        """Print one table line, with each value lined up under its column title."""
        # strict=False: some rows have fewer values than the table has columns
        parts = [f"{str(v):<{width}}" for (_, width), v in zip(columns, values, strict=False)]
        self.out(("  " + "  ".join(parts) + ("  " + tail if tail else "")).rstrip())

    def late_detail(self, r):
        """" (3 snake already moved, 1 too close to next move)" if the record has the split."""
        if r.get("late_answers") and "late_snake_moved" in r:
            return f" ({r['late_snake_moved']} snake already moved, {r['late_too_close']} too close to next move)"
        return ""

    def game_end(self, r):
        late = r.get("late_answers", 0)
        ending = ENDINGS.get(r.get("ended_by"), r.get("ended_by"))
        if r.get("crash_key_landed_late"):
            ending += " (the last key, a safe turn, reached the game too late)"
        parts = [f"score {r.get('score')}", f"{r.get('moves')} moves", ending]
        if self.is_jev:
            if "api_errors" in r:
                parts.append(plural(r["api_errors"], "API error"))
            parts.append(plural(late, "late answer") + self.late_detail(r))
        if r.get("keys_landed_late"):
            parts.append(plural(r["keys_landed_late"], "key") + " reached the game a step late")
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
        self.out("\n" + RULE)
        avg = r.get("average_score")
        self.out(f"Run finished {r['time'].replace('T', ' ')}: {r.get('games')} game(s), "
                 f"average score {avg if avg is not None else '-'}, best {r.get('best_score')}"
                 + (f" (game {r['best_game']})" if r.get("best_game") else ""))
        if self.is_jev:
            self.out(f"Late answers {r.get('late_answers')}{self.late_detail(r)}, "
                     f"{r.get('input_tokens', 0):,} input tokens, total cost ${r.get('total_cost_usd', 0):.4f}")
            if "api_errors" in r:
                self.out(f"API errors {r['api_errors']} (failed calls: timeouts, network errors, error replies)")
        if r.get("stopped_early"):
            self.out("STOPPED EARLY: " + r["stopped_early"].replace("\n", "\n               "))
        if r.get("best_screen_html"):
            self.out(f"Best game's screen: {r['best_screen_html']}")
            self.out(f"                    {r['best_screen_ans']}")
        self.out(RULE + "\n")


def game_settings():
    """The game's settings, read from snake.py (it sits next to this file)."""
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


MOVES_OFFERED = {
    "full": "safe & non-trapping moves only (0 ms short-circuit when only 1 safe move exists)",
    "safe": "1-step safe moves only (0 ms short-circuit when only 1 safe move exists)",
    "prompt": "all three non-reversal moves with lookahead descriptions",
    "off": "the three legal moves (never the reversal), shuffled each move",
}


def session_settings(args):
    """Everything that shapes this run. It becomes the first record in the log."""
    bot = {
        "player": args.player,
        "guard": args.guard,
        "assisted": args.player != "algorithm" and args.guard != "off",
        "compact_grid": args.compact_grid and args.guard != "off",  # what is REALLY sent
        "seed": args.seed,
        "games_requested": args.games or "no limit",
        "frame_poll_seconds": POLL_NEW_FRAME,
    }
    jev = None
    if args.player in ("jev", "openrouter"):
        bot["moves_offered"] = MOVES_OFFERED[args.guard]
        bot["late_answer_rule"] = ("if the snake has moved before the API answers, or the answer "
                                   f"arrives less than {KEY_MARGIN * 1000:.0f} ms before the next "
                                   "move, the answer is dropped (must-turn frames timeout early and "
                                   "use local safe fallback when guard is enabled)")
        if args.player == "openrouter":
            default_url = DEFAULT_OPENROUTER_JEV_URL if is_jev_model(args.model) else DEFAULT_OPENROUTER_CHAT_URL
            endpoint = os.environ.get("OPENROUTER_BASE_URL", "").strip() or default_url
            key_src = "OPENROUTER_API_KEY"
        else:
            endpoint = f"https://{JEV_HOST}{JEV_PATH}"
            key_src = ("TYPESAFE_API_KEY" if os.environ.get("TYPESAFE_API_KEY", "").strip()
                       else str(Path(args.key_file).expanduser()))
        jev = {
            "provider": args.player,
            "model_requested": args.model,
            "endpoint": endpoint,
            "api_key_source": key_src,  # only WHERE the key came from, never the key itself
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
        "environment": {"python": sys.version.split()[0],
                        "tmux": tmux("-V", check=False).stdout.strip()},
    }
