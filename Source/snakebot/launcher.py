"""The launcher: opens tmux with the game on top and the bot underneath."""

import os
import shlex
import shutil
import subprocess
import sys

from .config import HERE, MIN_TERMINAL_COLS, MIN_TERMINAL_ROWS, SESSION
from .tmuxio import tmux


def size_problem(cols, rows):
    """If the terminal is too small for the full board, say so. Otherwise return None.
    (A window that is too small makes the game quit at once, which looks like a silent crash.)"""
    if cols >= MIN_TERMINAL_COLS and rows >= MIN_TERMINAL_ROWS:
        return None
    return (f"Terminal too small: need at least {MIN_TERMINAL_COLS} columns x {MIN_TERMINAL_ROWS} rows, "
            f"but this one is {cols} x {rows}.\nMake the window bigger, then run it again.")


def key_handoff_file(key):
    """Put the secret key in a private temp file (only you can read it) for the bot inside tmux
    to pick up and delete. This keeps the key off the command line, where other users could see it."""
    import tempfile
    folder = os.environ.get("XDG_RUNTIME_DIR")
    fd, path = tempfile.mkstemp(prefix="snake_bot_key_", dir=folder if folder and os.path.isdir(folder) else None)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    return path


def launch(extra_args):
    """Open a tmux session: the game on top, and a second copy of this bot underneath."""
    w, h = shutil.get_terminal_size()
    problem = size_problem(w, h)
    if problem:
        sys.exit(problem)
    if subprocess.run(["tmux", "has-session", "-t", SESSION], capture_output=True).returncode == 0:
        sys.exit(f"A '{SESSION}' tmux session already exists. "
                 f"Attach with: tmux attach -t {SESSION}   or end it with: tmux kill-session -t {SESSION}")

    if tmux("show-options", "-gv", "status", check=False).stdout.strip() != "off":
        h -= 1  # tmux's status bar uses one line
    py = shlex.quote(sys.executable)
    game_cmd = f"{py} {shlex.quote(str(HERE / 'snake.py'))}"

    # Make the bot pane first, then put the game above it at its final size.
    # (The game picks its board size when it starts, so it must not be resized later.)
    bot_pane = tmux("new-session", "-d", "-s", SESSION, "-x", str(w), "-y", str(h),
                    "-P", "-F", "#{pane_id}").stdout.strip()
    game_pane = tmux("split-window", "-b", "-t", bot_pane, "-l", str(max(h - 8, 10)),
                     "-P", "-F", "#{pane_id}", game_cmd).stdout.strip()
    bot_cmd = " ".join([py, shlex.quote(str(HERE / "snake_bot.py")), "--target", game_pane,
                        *map(shlex.quote, extra_args)])
    # If the bot stops with an error, keep its pane open so you can read the message.
    bot_cmd += ('; code=$?; if [ $code -ne 0 ]; then printf "\\nThe bot stopped (exit code %s). '
                'Press Enter to close this pane. " $code; read _; fi')
    tmux("respawn-pane", "-k", "-t", bot_pane, bot_cmd)
    tmux("select-pane", "-t", game_pane)

    if os.environ.get("TMUX"):
        tmux("switch-client", "-t", SESSION)
    else:
        os.execvp("tmux", ["tmux", "attach", "-t", SESSION])
