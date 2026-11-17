"""The Jev player: asks TypeSafe's Jev model for every move."""

import os

from ..config import DEFAULT_GUARD, JEV_HOST, JEV_PATH, OPENROUTER_BILLING_URL, OPENROUTER_HOST
from ..env import load_api_key
from .base import BaseAIPlayer
from .models import normalize_openrouter_model
from .wire import parse_systemone, systemone_body


class JevPlayer(BaseAIPlayer):
    """Asks TypeSafe's Jev model for every move. It calls TypeSafe directly, or goes through
    OpenRouter when only OPENROUTER_API_KEY is set."""

    shows_confidence = True

    def __init__(self, key_file, model, guard=DEFAULT_GUARD, compact_grid=True):
        ts_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if or_key == "your_openrouter_api_key_here":
            or_key = ""
        self.via_openrouter = bool(or_key and not ts_key)
        super().__init__(model=normalize_openrouter_model(model) if self.via_openrouter else model,
                         guard=guard, compact_grid=compact_grid)
        self.key = load_api_key(key_file, player="jev")
        self.host = OPENROUTER_HOST if self.via_openrouter else JEV_HOST
        self.path = "/api/v1/systemone" if self.via_openrouter else JEV_PATH
        self.label = "Jev"
        if self.via_openrouter:
            self.billing_url = OPENROUTER_BILLING_URL
            self.key_hint = "OPENROUTER_API_KEY in .env"
            self.fail_hint = "Check the network connection and the OpenRouter dashboard, then start the bot again."
        else:
            self.key_hint = "the key in the key file (or TYPESAFE_API_KEY)"
            self.fail_hint = "Check the network connection and the TypeSafe console, then start the bot again."

    def build_request(self, s, board, options, descriptions):
        return systemone_body(self.model, board, s.cols, s.rows, descriptions)

    def parse_reply(self, payload, options):
        return parse_systemone(payload, options)
