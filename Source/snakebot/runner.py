"""The main loop: watch the screen, ask the player for a move, press the key, keep score."""

import shutil
import statistics
import time

from .config import FAST_PATH_MARGIN, KEY_MARGIN, POLL_NEW_FRAME, REDRAW_RETRY, SPEEDUP, START_DELAY, VERSION
from .geometry import KEY_NAMES
from .players.base import BaseAIPlayer, JevStop
from .prompts import JEV_INSTRUCTIONS
from .report import save_best_screen
from .screen import read_screen
from .tmuxio import capture, press


class Tally:
    """A scoreboard of counters. One is kept for the current game, and one for the whole run."""

    def __init__(self):
        self.moves = self.late = self.tokens = self.incomplete = self.errors = self.keys_late = 0
        self.cost = 0.0
        self.late_counts = {"snake moved": 0, "too close": 0}

    def add(self, game):
        """Add a finished game into these totals. (Errors are counted live, so they aren't added here.)"""
        self.late += game.late
        self.tokens += game.tokens
        self.cost += game.cost
        for reason, n in game.late_counts.items():
            self.late_counts[reason] += n


def late_reason(target, last_frame, last_frame_t, step, game):
    """Did the AI answer too late? Returns why, or None if the answer is still good.
      "snake moved"  the board changed before the answer came
      "too close"    less than KEY_MARGIN was left before the next step"""
    elapsed = time.monotonic() - last_frame_t
    if elapsed <= step - KEY_MARGIN - FAST_PATH_MARGIN:
        return None  # plenty of time left: skip the extra screen look
    s_now = None
    for _ in range(10):  # look again, skipping photos taken mid-redraw
        now = capture(target)
        s_now = read_screen(now) if now else None
        if s_now is None or s_now.over or s_now.complete():
            break
        game.incomplete += 1
        time.sleep(REDRAW_RETRY)
    if s_now is None or s_now.frame_id() != last_frame:
        return "snake moved"
    return "too close" if elapsed > step - KEY_MARGIN else None


def end_game(log, s, text, sent_key, game, total, games, best_shot, frame_times):
    """Write the game_end log record. Returns (why the game ended, best_shot so far)."""
    first_frame_t, last_frame_t = frame_times
    # The game-over photo shows the snake exactly where it crashed from, so use it to find the cause.
    pressed = sent_key[1] if sent_key and sent_key[0] == s.frame_id() else None
    if "YOU WIN" in text:
        cause, key_late_at_end = "won", False
    else:
        cause, key_late_at_end = s.crash_cause(pressed)
    if key_late_at_end:
        game.keys_late += 1
    if best_shot is None or s.score > best_shot["score"]:  # on a tie, the first game stays the best
        best_shot = {"text": text, "game": games, "score": s.score, "cause": cause,
                     "moves": game.moves, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    measured = None
    if game.moves > 1 and first_frame_t is not None:
        measured = round((last_frame_t - first_frame_t) / (game.moves - 1), 4)  # real seconds per move
    log.write("game_end", game=games, score=s.score, moves=game.moves,
              ended_by=cause, api_errors=game.errors, late_answers=game.late,
              late_snake_moved=game.late_counts["snake moved"],
              late_too_close=game.late_counts["too close"], keys_landed_late=game.keys_late,
              crash_key_landed_late=key_late_at_end, final_board=s.grid_text(),
              incomplete_reads_skipped=game.incomplete,
              measured_seconds_per_move=measured, input_tokens=game.tokens,
              cost_usd=round(game.cost, 6), session_total_cost_usd=round(total.cost, 6))
    return cause, best_shot


def play(target, max_games, hold, player, log, settings, shot_base):
    """Watch the game and play it until max_games are done (0 = no limit) or the game closes.

    The loop does this over and over:
      1. take a photo of the screen
      2. if the game is over, record it and press R to restart
      3. if there is a new board, ask the player for a move and press the key
    With hold=True the bot stays open at the end so you can read the results.
    The best game's final screen is saved as shot_base + "_best.html" and "_best.ans"."""
    is_jev = isinstance(player, BaseAIPlayer)
    player_label = player.label if is_jev else "algorithm"
    finished = started = False  # started: session_start is logged once we've seen the board
    first_frame_t = last_frame_t = None
    games = best = total_score = 0
    total, game = Tally(), Tally()  # the whole run, and the current game
    last_frame = None
    sent_key = None  # (board fingerprint, direction) of the last key pressed, so we can check it worked
    status = ""
    best_shot = shot_paths = stop_reason = None

    def show(msg):
        """Print a one-line status that rewrites itself in place."""
        nonlocal status
        msg = msg[:max(shutil.get_terminal_size().columns - 1, 20)]  # a wrapped line can't be rewritten
        if msg != status:
            status = msg
            print("\r\033[K" + msg, end="", flush=True)

    model_info = f", model={player.model}, guard={player.guard}" if is_jev else ""
    print(f"Snake bot {VERSION} ({type(player).__name__}{model_info}) watching tmux pane {target}.  "
          f"Press Q in the game to quit.")
    print(f"Logging to {log.path}\n    and {log.text_path} (plain text)\n" if log.path else "Logging is off.\n")
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
                if settings.get("jev"):  # log the instructions exactly as the AI gets them
                    settings["jev"]["instructions"] = JEV_INSTRUCTIONS.format(cols=s.cols, rows=s.rows)
                log.write("session_start", **settings, target=target)

            if s.over:
                if game.moves:  # only count games the bot really played
                    games += 1
                    total_score += s.score
                    best = max(best, s.score)
                    total.add(game)
                    cause, best_shot = end_game(log, s, text, sent_key, game, total, games,
                                                best_shot, (first_frame_t, last_frame_t))
                    money = f"  ${game.cost:.4f}  (session ${total.cost:.4f})" if is_jev else ""
                    print(f"\rGame {games}: score {s.score:<3} {cause:<4} moves {game.moves:<4}"
                          f"{f' late {game.late}' if is_jev else ''}{money}"
                          f"  | avg {total_score / games:.1f} best {best}"
                          f"{f'  errors {total.errors}' if is_jev else ''}\033[K")
                    status = ""
                    if max_games and games >= max_games:
                        finished = True
                        break
                    time.sleep(1.5)
                press(target, "r")  # R starts a new game
                if hasattr(player, "new_game"):
                    player.new_game()
                game = Tally()
                last_frame = sent_key = first_frame_t = last_frame_t = None
                time.sleep(0.3)
                continue

            if s.paused:
                show("Game paused - press P in the game to resume.")
                time.sleep(0.1)
                continue

            if s.head is None or s.frame_id() == last_frame:  # nothing new on the board yet
                time.sleep(POLL_NEW_FRAME)
                continue
            if not s.complete():  # we caught the game mid-redraw, so look again
                game.incomplete += 1
                time.sleep(REDRAW_RETRY)
                continue

            # ---- A new board! Time to pick a move. ----
            last_frame = s.frame_id()
            last_frame_t = time.monotonic()
            if first_frame_t is None:
                first_frame_t = last_frame_t
            game.moves += 1
            # Did the key we pressed LAST time work? If the snake isn't facing that way, it arrived late.
            key_missed = bool(sent_key) and s.heading() != sent_key[1]
            if key_missed:
                game.keys_late += 1
            sent_key = None

            step = START_DELAY * SPEEDUP ** s.score  # how long the game gives us for this move
            budget = (step - KEY_MARGIN) - (time.monotonic() - last_frame_t)
            d, info = player.choose(s, step_budget=budget)
            info.pop("fallback_dir", None)
            if "error" in info:
                game.errors += 1
                total.errors += 1
            game.tokens += info.get("input_tokens", 0)
            game.cost += info.get("cost_usd", 0.0)

            reason = None
            if d is not None and is_jev and not info.get("forced"):
                reason = late_reason(target, last_frame, last_frame_t, step, game)
                if reason:  # too late: throw the answer away, the snake keeps going straight
                    game.late += 1
                    game.late_counts[reason] += 1
                    d = None

            pressed = None
            if d is not None and d != s.heading():  # no need to press a key for the way we already go
                press(target, KEY_NAMES[d])
                pressed = KEY_NAMES[d]
                sent_key = (last_frame, d)

            # Log AFTER pressing, so writing to disk can never make a move late.
            log.write("move", game=games + 1, move=game.moves, score=s.score,
                      late=reason is not None, late_reason=reason, key_pressed=pressed,
                      previous_key_landed_late=key_missed, **info)
            if is_jev and player.stop:  # out of credits, bad key, or too many failures
                raise JevStop(player.stop)

            extra = ""
            if is_jev:
                med = f"  {statistics.median(player.times):.0f} ms" if player.times else ""
                extra = (f"  late {game.late}  errors {total.errors}{med}"
                         f"  ${total.cost + game.cost:.4f}   last: {player.last}")
            show(f"Game {games + 1}: score {s.score}  moves {game.moves}{extra}")
    except JevStop as e:
        stop_reason = str(e)
        raise
    finally:  # runs even if we stop early, so the log and best screen are always saved
        if best_shot:
            best_shot["games"] = games
            try:
                shot_paths = save_best_screen(shot_base, best_shot, player_label)
            except OSError as e:
                print(f"\nCould not save the best game's screen: {e}")
        log.write("session_end", games=games,
                  average_score=round(total_score / games, 2) if games else None,
                  best_score=best, api_errors=total.errors, late_answers=total.late,
                  late_snake_moved=total.late_counts["snake moved"],
                  late_too_close=total.late_counts["too close"],
                  input_tokens=total.tokens, total_cost_usd=round(total.cost, 6),
                  best_game=best_shot["game"] if best_shot else None,
                  best_screen_html=str(shot_paths[0]) if shot_paths else None,
                  best_screen_ans=str(shot_paths[1]) if shot_paths else None,
                  stopped_early=stop_reason)
        if shot_paths and not finished:
            print(f"\nBest game's screen saved to {shot_paths[0]}")

    if finished:
        money = f", total cost ${total.cost:.4f}, API errors {total.errors}" if is_jev else ""
        print(f"\nFinished {games} game(s): average score {total_score / games:.1f}, best {best}{money}.")
        if shot_paths:
            print(f"Best game (game {best_shot['game']}) screen saved to:\n  {shot_paths[0]}\n  {shot_paths[1]}")
        if hold:
            print("Press Q in the game to close.")
            while capture(target) is not None:  # wait here until the game is closed
                time.sleep(0.5)
