"""Settings: every fixed number and web address in one place.

If you want to change how fast the bot reacts or which website it calls, look here first.
This module imports nothing else from the bot."""

import sys
from pathlib import Path

# Borrow the game's own settings so the bot and the game always agree.
try:
    from snake import SPEEDUP, START_DELAY, START_LENGTH
except Exception as _e:  # noqa: BLE001
    START_LENGTH, START_DELAY, SPEEDUP = 4, 0.3, 1.0
    print(f"snake_bot: could not read snake.py ({_e}); using the game's default settings.", file=sys.stderr)

VERSION = "1.7"

HERE = Path(__file__).resolve().parent.parent  # the Source folder

SESSION = "snakebot"  # name of the tmux session we create

# ---- Settings you might want to change --------------------------------------------
DEFAULT_KEY_FILE = "jev_key.txt"

JEV_HOST, JEV_PATH = "api.typesafe.ai", "/v1/systemone"

OPENROUTER_HOST = "openrouter.ai"

DEFAULT_OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_OPENROUTER_JEV_URL = "https://openrouter.ai/api/v1/systemone"

DEFAULT_OPENROUTER_MODEL = "typesafe/jev-latest"

BILLING_URL = "https://console.typesafe.ai/setting"

OPENROUTER_BILLING_URL = "https://openrouter.ai/settings/credits"

PRICE_PER_TOKEN = 0.042 / 1_000_000  # Jev's published price: $0.042 per million input tokens

GUARDS = ("full", "safe", "prompt", "off")

DEFAULT_GUARD = "off"  # "off" = the fair test; the others are "assisted"

REQUEST_TIMEOUT = 1.0     # seconds to wait for the AI. The snake moves every 0.3 s, so late answers are useless.

MAX_ERRORS_IN_A_ROW = 10  # this many failed AI calls in a row stops the run (about 3 seconds of play)

# ---- Timing (all in seconds) ------------------------------------------------------
# A key press must arrive this long BEFORE the snake's next step, or it lands a step late.
KEY_MARGIN = 0.040

POLL_NEW_FRAME = 0.005        # nap between looks at the screen while waiting for a new frame

REDRAW_RETRY = 0.002          # nap before looking again if we caught the game mid-redraw

FAST_PATH_MARGIN = 0.040      # if we have this much time to spare, skip the "did the snake move?" look

MUST_TURN_MIN_TIMEOUT = 0.08  # shortest wait for the AI when the snake MUST turn right now

MUST_TURN_RESERVE = 0.030     # time saved for pressing the key on those frames

# The smallest terminal that fits the full 40 x 20 board. A smaller window gives a smaller
# board, which would quietly change the results, so the launcher refuses to start in one.
MIN_TERMINAL_COLS, MIN_TERMINAL_ROWS = 90, 33
DEFAULT_LOG_DIR = HERE.parent / "Outputs"  # where logs and best-game screens go
