"""The OpenRouter player: asks a model on OpenRouter for every move."""

import json
import os
from urllib.parse import urlparse

from ..config import (
    DEFAULT_GUARD,
    DEFAULT_OPENROUTER_CHAT_URL,
    DEFAULT_OPENROUTER_JEV_URL,
    OPENROUTER_BILLING_URL,
    OPENROUTER_HOST,
)
from ..env import load_api_key
from ..prompts import JEV_INSTRUCTIONS
from .base import BaseAIPlayer
from .models import is_jev_model, normalize_openrouter_model
from .wire import parse_chat, parse_systemone, systemone_body


class OpenRouterPlayer(BaseAIPlayer):
    """Asks a model on OpenRouter for every move. Jev models use the "systemone" service;
    any other model is asked in plain chat."""

    label = "OpenRouter"
    billing_url = OPENROUTER_BILLING_URL
    key_hint = "OPENROUTER_API_KEY in .env"
    fail_hint = "Check your network connection, OPENROUTER_API_KEY, and OPENROUTER_MODEL in .env."

    def __init__(self, key_file, model, guard=DEFAULT_GUARD, compact_grid=True, cot=None):
        super().__init__(model=normalize_openrouter_model(model), guard=guard, compact_grid=compact_grid)
        self.key = load_api_key(key_file, player="openrouter")
        self.use_systemone = is_jev_model(self.model)
        self.shows_confidence = self.use_systemone
        default_url = DEFAULT_OPENROUTER_JEV_URL if self.use_systemone else DEFAULT_OPENROUTER_CHAT_URL
        custom_url = os.environ.get("OPENROUTER_BASE_URL", "").strip()
        # A Jev model can't use the chat address, so quietly switch to the right one.
        if self.use_systemone and custom_url.rstrip("/") == DEFAULT_OPENROUTER_CHAT_URL.rstrip("/"):
            custom_url = ""
        parsed = urlparse(custom_url or default_url)
        self.host = parsed.netloc or OPENROUTER_HOST
        self.path = parsed.path or ("/api/v1/systemone" if self.use_systemone else "/api/v1/chat/completions")
        if cot is None:  # "cot" = let the model jot a short plan before answering
            self.cot = os.environ.get("OPENROUTER_COT", "1").strip().lower() not in ("0", "false", "no", "off")
        else:
            self.cot = bool(cot)

    def build_request(self, s, board, options, descriptions):
        if self.use_systemone:
            return systemone_body(self.model, board, s.cols, s.rows, descriptions)
        opts_str = ", ".join(options)
        if self.cot:
            schema_hint = (f'Respond ONLY with a valid JSON object: {{"plan": "<max 6 words lookahead>", '
                           f'"move": "<one of: {opts_str}>"}}')
        else:
            schema_hint = f'Respond ONLY with a valid JSON object: {{"move": "<one of: {opts_str}>"}}'
        sys_prompt = JEV_INSTRUCTIONS.format(cols=s.cols, rows=s.rows) + " " + schema_hint
        crit_lines = "\n".join(f"- {name}: {descriptions[name]}" for name in options)
        user_prompt = f"Board:\n{board}\n\nLegal moves:\n{crit_lines}\n\nPick the best move from [{opts_str}]."
        return json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": sys_prompt},
                         {"role": "user", "content": user_prompt}],
            "temperature": 0,  # no randomness: same board, same answer
            "max_tokens": 55 if self.cot else 20,
            "response_format": {"type": "json_object"},
            "provider": {"sort": "latency"},  # prefer the fastest provider
        })

    def parse_reply(self, payload, options):
        return parse_systemone(payload, options) if self.use_systemone else parse_chat(payload, options)
