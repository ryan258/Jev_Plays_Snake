"""The command line: reads your options, fills in defaults, and starts a run."""

import argparse
import os
import random
import shutil
import sys
import time
from pathlib import Path

from .config import (
    DEFAULT_GUARD,
    DEFAULT_KEY_FILE,
    DEFAULT_LOG_DIR,
    DEFAULT_OPENROUTER_MODEL,
    GUARDS,
    VERSION,
)
from .env import key_env_var, load_api_key, load_dotenv
from .launcher import key_handoff_file, launch
from .players import make_player
from .players.base import JevStop
from .runlog import Log, session_settings
from .runner import play


def apply_env_defaults(args):
    """For every option not typed on the command line, use .env / the environment, then a default."""
    if args.player is None:
        env_player = os.environ.get("SNAKE_PLAYER", "").strip().lower()
        if env_player in ("jev", "openrouter", "algorithm"):
            args.player = env_player
        elif os.environ.get("OPENROUTER_API_KEY", "").strip():
            args.player = "openrouter"
        else:
            args.player = "jev"
    if args.guard is None:
        env_guard = os.environ.get("SNAKE_GUARD", DEFAULT_GUARD).strip().lower()
        args.guard = env_guard if env_guard in GUARDS else DEFAULT_GUARD
    if args.compact_grid is None:
        args.compact_grid = os.environ.get("SNAKE_COMPACT_GRID", "1").strip().lower() not in ("0", "false", "no", "off")
    if args.model is None:
        if args.player == "openrouter":
            args.model = os.environ.get("OPENROUTER_MODEL", "").strip() or DEFAULT_OPENROUTER_MODEL
        else:
            args.model = os.environ.get("JEV_MODEL", "").strip() or "jev-latest"


def build_parser():
    p = argparse.ArgumentParser(description="A bot that plays snake.py through tmux.")
    p.add_argument("--player", choices=("jev", "openrouter", "algorithm"), default=None,
                   help="who picks the moves (default: from .env, else jev)")
    p.add_argument("--env-file", default=None,
                   help="path to a .env file (default: searches ./.env, Source/.env, ../.env)")
    p.add_argument("--guard", choices=GUARDS, default=None,
                   help="off = raw board, the fair test (default: SNAKE_GUARD in .env, else 'off'); "
                        "safe/prompt/full give the model hints (assisted runs)")
    p.add_argument("--seed", type=int, default=None, help="seed the random tie-breaks, so a run can be repeated")
    p.add_argument("--compact-grid", dest="compact_grid", action="store_true", default=None,
                   help="send a compact board to cut token use (default: on)")
    p.add_argument("--no-compact-grid", dest="compact_grid", action="store_false",
                   help="send the classic space-padded board")
    p.add_argument("--cot", dest="cot", action="store_true", default=None,
                   help="OpenRouter chat models: write a short plan before the move")
    p.add_argument("--no-cot", dest="cot", action="store_false",
                   help="OpenRouter chat models: answer with the move only (fastest)")
    p.add_argument("--target", help="tmux pane running the game (default: open a new session)")
    p.add_argument("--games", type=int, default=0, metavar="N",
                   help="number of games to play, then stop (default: keep going until Q)")
    p.add_argument("--hold", action="store_true", help=argparse.SUPPRESS)  # set by the launcher
    # The next two are set by the launcher: the secret key travels in a private file, not the command line.
    p.add_argument("--key-handoff", help=argparse.SUPPRESS)
    p.add_argument("--key-handoff-var", help=argparse.SUPPRESS)
    p.add_argument("--key-file", default=DEFAULT_KEY_FILE,
                   help=f"file holding the API key (default: {DEFAULT_KEY_FILE} in the current directory)")
    p.add_argument("--model", default=None, help="AI model to ask (default: OPENROUTER_MODEL or JEV_MODEL from .env)")
    p.add_argument("--log", help="log file to append to (default: a new file in the log directory)")
    p.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR),
                   help=f"where logs and best-game screens go (default: {DEFAULT_LOG_DIR})")
    p.add_argument("--version", action="version", version=f"snake_bot.py {VERSION}")
    p.add_argument("--no-log", action="store_true", help="don't keep a log")
    return p


def main():
    args = build_parser().parse_args()
    loaded_env = load_dotenv(args.env_file)
    apply_env_defaults(args)

    if args.games < 0:
        sys.exit("--games must be 0 (no limit) or more")
    # Turn these into full paths NOW, so the copy of the bot inside tmux finds the same files.
    args.key_file = str(Path(args.key_file).expanduser().resolve())
    log_dir = Path(args.log_dir).expanduser().resolve()

    if not shutil.which("tmux"):
        sys.exit("tmux is not installed. Install it with: sudo apt install tmux")

    if not args.target:
        # First run (no --target yet): check the key now, then open tmux and start a second copy of ourselves.
        if args.player in ("jev", "openrouter"):
            load_api_key(args.key_file, player=args.player)
        extra = ["--player", args.player, "--key-file", args.key_file, "--model", args.model,
                 "--guard", args.guard, "--compact-grid" if args.compact_grid else "--no-compact-grid"]
        if loaded_env:
            extra += ["--env-file", str(loaded_env)]
        if args.cot is not None:
            extra.append("--cot" if args.cot else "--no-cot")
        if args.seed is not None:
            extra += ["--seed", str(args.seed)]
        env_key_var = key_env_var(args.player)
        if args.player in ("jev", "openrouter") and os.environ.get(env_key_var, "").strip():
            extra += ["--key-handoff", key_handoff_file(os.environ[env_key_var].strip()),
                      "--key-handoff-var", env_key_var]
        extra += ["--games", str(args.games), "--hold", "--log-dir", str(log_dir)]
        if args.no_log:
            extra.append("--no-log")
        elif args.log:
            extra += ["--log", str(Path(args.log).resolve())]
        launch(extra)
        return

    # Second run (inside tmux, with --target): this copy does the actual playing.
    stamp = f"{args.player}_{time.strftime('%Y%m%d_%H%M%S')}"
    log_path = None if args.no_log else (args.log or log_dir / f"{stamp}.jsonl")
    log = Log(log_path)
    # The best-game screen is saved next to the log, with the same name.
    shot_base = Path(log_path).with_suffix("") if log_path else log_dir / stamp
    if args.seed is not None:
        random.seed(args.seed)
    if args.key_handoff:  # pick up the secret key from its private file, then delete the file
        try:
            os.environ[args.key_handoff_var or key_env_var(args.player)] = Path(args.key_handoff).read_text().strip()
        except OSError as e:
            sys.exit(f"Could not read the API key passed by the launcher: {e}")
        finally:
            Path(args.key_handoff).unlink(missing_ok=True)
    player = make_player(args)
    try:
        play(args.target, args.games, args.hold, player=player, log=log,
             settings=session_settings(args), shot_base=shot_base)
    except KeyboardInterrupt:
        print()
    except JevStop as e:
        sys.exit(f"\n\n{e}")
    finally:
        player.close()
        log.close()
