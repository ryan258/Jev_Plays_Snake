"""The steps every AI player shares: ask, wait, read the answer, and handle errors.

A player only has to say how to write the question and read the answer."""

import http.client
import json
import os
import time

from ..config import (
    BILLING_URL,
    DEFAULT_GUARD,
    MAX_ERRORS_IN_A_ROW,
    MUST_TURN_MIN_TIMEOUT,
    MUST_TURN_RESERVE,
    REQUEST_TIMEOUT,
)
from ..geometry import KEY_NAMES, NAME_DIRS
from ..guard import analyze_candidates
from ..pathfinding import Tracker


class JevStop(Exception):
    """Raised when the AI can't go on, so the whole run must stop. The message says why."""


def jev_message(payload):
    """Pull the human-readable message out of an error reply (if there is one)."""
    if isinstance(payload, dict):
        if isinstance(payload.get("error"), dict):
            err = payload["error"]
            return str(err.get("message") or err.get("code") or err)[:300]
        detail = payload.get("detail")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("error_type") or detail)
        if detail is not None:
            return str(detail)[:300]
    return str(payload)[:300]


class BaseAIPlayer:
    """The steps every AI player shares. choose() does all the common work:
    pick which moves to offer, ask the AI, handle errors, and hand back a direction.

    A subclass only has to say how to WRITE the question (build_request)
    and how to READ the answer (parse_reply)."""

    label = "AI"                   # the provider's name, used in messages
    billing_url = BILLING_URL
    key_hint = "the API key"       # where to look if the key is rejected
    fail_hint = "Check the network connection, then start the bot again."
    shows_confidence = False       # does the answer carry a real confidence number?

    def __init__(self, model, guard=DEFAULT_GUARD, compact_grid=True):
        self.model = model
        self.guard = guard
        self.compact_grid = compact_grid and guard != "off"
        self.conn = None           # one internet connection, reused so each call is fast
        self.conn_timeout = None
        self.times = []            # how long each answer took (ms)
        self.last = ""             # a short summary of the last move, for the status line
        self.errors_in_a_row = 0
        self.stop = None           # set to a message when the run must end
        self.tracker = Tracker()
        self.since_food = 0        # moves since the snake last ate
        self.last_score = 0
        self.key = None
        self.host = self.path = None

    def new_game(self):
        self.tracker = Tracker()
        self.since_food = 0
        self.last_score = 0

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001 - closing is best-effort
                pass
            self.conn = self.conn_timeout = None

    # -- the two things each provider does differently ---------------------------

    def build_request(self, s, board, options, descriptions):
        """Return the request body (text) to send for this board."""
        raise NotImplementedError

    def parse_reply(self, payload, options):
        """Return (answer, input tokens, cost in dollars). Raise an error if the reply is broken."""
        raise NotImplementedError

    # -- everything else is shared -------------------------------------------------

    def headers(self):
        h = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if self.host and self.host.endswith("openrouter.ai"):
            h["X-Title"] = "Jev_Plays_Snake"
            referer = os.environ.get("OPENROUTER_REFERER", "").strip()  # optional "who am I" header
            if referer:
                h["HTTP-Referer"] = referer
        return h

    def post(self, body, timeout):
        """Send the request. Returns (HTTP status number, the reply as a dict)."""
        if self.conn is None:
            self.conn = http.client.HTTPSConnection(self.host, timeout=timeout)
            self.conn_timeout = timeout
        elif self.conn.sock is not None and self.conn_timeout != timeout:
            self.conn.sock.settimeout(timeout)
            self.conn_timeout = timeout
        self.conn.request("POST", self.path, body=body, headers=self.headers())
        resp = self.conn.getresponse()
        return resp.status, json.loads(resp.read() or b"{}")

    def failed(self, info, last, error, fallback_dir=None, must_turn=False):
        """A call failed. Count it, and stop the whole run if too many failed in a row.
        If the snake MUST turn now, use the path-finder's move instead (when the guard allows)."""
        self.last = last
        info["error"] = error
        self.errors_in_a_row += 1
        if self.errors_in_a_row >= MAX_ERRORS_IN_A_ROW and not self.stop:
            self.stop = (f"{self.label} failed {self.errors_in_a_row} calls in a row, so the run "
                         f"was stopped.\nLast error: {error}\n{self.fail_hint}")
        if must_turn and fallback_dir is not None and self.guard in ("full", "safe"):
            info["fallback_used"] = True
            return fallback_dir, info
        return None, info

    def stop_message(self, status, payload):
        """For errors that make going on pointless (no credits, bad key), return the message. Else None."""
        detail = payload.get("detail") if isinstance(payload, dict) else None
        billing = status == 402 or (isinstance(detail, dict) and detail.get("error_type") == "billing_error")
        if billing:
            return (f"{self.label} stopped the run: the account is out of API credits (HTTP {status}).\n"
                    f"{self.label} said: {jev_message(payload)}\n"
                    f"Add credits at {self.billing_url}, then start the bot again.")
        if status == 401:
            return (f"{self.label} rejected the API key (HTTP 401).\n"
                    f"{self.label} said: {jev_message(payload)}\n"
                    f"Check {self.key_hint}, then start the bot again.")
        return None

    def choose(self, s, step_budget=None):
        """Look at the board and pick a move. Returns (direction or None, info for the log).
        None means "don't press anything": the snake just keeps going straight."""
        self.since_food = 0 if s.score > self.last_score else self.since_food + 1
        self.last_score = s.score
        options, descriptions, fallback_dir = analyze_candidates(
            s, self.tracker, self.since_food, guard=self.guard)
        board = s.grid_text(compact=self.compact_grid)
        info = {"board": board, "options": options, "fallback_dir": fallback_dir}

        # Only one move left? No need to ask the AI. Answer instantly.
        if self.guard in ("full", "safe") and len(options) == 1:
            choice = options[0]
            ans = {"choice": choice, "confidence": 1.0, "probabilities": {choice: 1.0}}
            info.update(model=f"{self.model} (forced-guard)", answer=ans,
                        input_tokens=0, cost_usd=0.0, response_ms=0.0, forced=True)
            self.last = f"{choice:<5} forced   0 ms"
            return NAME_DIRS[choice], info

        # "Must turn" = going straight would crash. Then we can't wait long for the AI.
        heading = s.heading()
        must_turn = heading is not None and KEY_NAMES.get(heading) not in options
        timeout = REQUEST_TIMEOUT
        if must_turn and self.guard in ("full", "safe") and step_budget is not None:
            timeout = max(MUST_TURN_MIN_TIMEOUT, min(REQUEST_TIMEOUT, step_budget - MUST_TURN_RESERVE))

        body = self.build_request(s, board, options, descriptions)
        t = time.perf_counter()
        try:
            status, payload = self.post(body, timeout)
        except (http.client.HTTPException, OSError, ValueError) as e:
            self.close()  # the connection may be broken, so start fresh next time
            return self.failed(info, f"network error: {type(e).__name__}",
                               f"{type(e).__name__}: {e}", fallback_dir, must_turn)
        ms = (time.perf_counter() - t) * 1000
        info["response_ms"] = round(ms, 1)

        if status != 200:
            error = f"HTTP {status}: {jev_message(payload)}"
            stop = self.stop_message(status, payload)
            if stop:
                info["error"] = error
                self.stop = stop
                return None, info
            return self.failed(info, f"{self.label} error {status}", error, fallback_dir, must_turn)

        try:
            ans, tokens, cost_usd = self.parse_reply(payload, options)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
            return self.failed(info, f"unexpected reply from {self.label}",
                               f"unexpected reply ({type(e).__name__}: {e}): {str(payload)[:200]}",
                               fallback_dir, must_turn)
        choice = ans["choice"]
        self.errors_in_a_row = 0
        self.times.append(ms)
        info.update(model=payload.get("model") or self.model, answer=ans,
                    input_tokens=tokens, cost_usd=cost_usd)
        conf = f"conf {float(ans.get('confidence', 0)):.2f}  " if self.shows_confidence else ""
        self.last = f"{choice:<5} {conf}{ms:4.0f} ms"
        return NAME_DIRS[choice], info
