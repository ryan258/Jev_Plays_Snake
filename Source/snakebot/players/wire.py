"""The shape of the messages: how to write a question to the AI and read its answer.

No internet code lives here, only text in and text out. That makes it easy to test."""

import json
import re

from ..config import PRICE_PER_TOKEN
from ..prompts import JEV_INSTRUCTIONS


def systemone_body(model, board, cols, rows, descriptions):
    """The question we send to TypeSafe's multiple-choice ("systemone") service."""
    return json.dumps({
        "model": model,
        "state": board,
        "questions": {"move": {
            "type": "choice",
            "instructions": JEV_INSTRUCTIONS.format(cols=cols, rows=rows),
            "criteria": descriptions,
        }},
    })


def parse_systemone(payload, options):
    """Read a systemone answer. Returns (answer, input tokens, cost in dollars).
    Raises an error if the answer is broken or picks a move we didn't offer."""
    ans = payload["answers"]["move"]
    if ans["choice"] not in options:
        raise ValueError(f"choice {ans['choice']!r} was not one of the options offered")
    usage = payload.get("usage") or {}
    tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    cost = float(usage.get("cost") or tokens * PRICE_PER_TOKEN)
    float(ans.get("confidence", 0))  # a garbled confidence means the whole answer can't be trusted
    return ans, tokens, cost


def parse_chat(payload, options):
    """Read an answer from a chat model. Returns (answer, input tokens, cost in dollars).

    JSON answers must have a valid "move". Plain-sentence answers count only if they name
    exactly ONE direction, so a stray "up" in some chatter can't pick the move."""
    content = (payload["choices"][0]["message"].get("content") or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL).strip()  # drop ``` fences
    choice = plan_text = None
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        raw_move = str(parsed.get("move") or parsed.get("choice") or "").strip().capitalize()
        choice = raw_move if raw_move in options else None
        plan_text = parsed.get("plan")
    else:
        named = {m.capitalize() for m in re.findall(r"\b(Up|Down|Left|Right)\b", content, re.IGNORECASE)}
        if len(named) == 1:
            choice = named.pop()
    if choice not in options:
        raise ValueError(f"reply {content!r} did not pick one of {options}")

    usage = payload.get("usage") or {}
    tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    cost = float(usage.get("cost") or tokens * PRICE_PER_TOKEN)
    ans = {"choice": choice, "confidence": 1.0,
           "probabilities": {opt: (1.0 if opt == choice else 0.0) for opt in options}}
    if plan_text:
        ans["plan"] = str(plan_text)[:120]
    return ans, tokens, cost
