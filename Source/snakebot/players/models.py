"""Model names: is this one of TypeSafe's Jev models, and what is its OpenRouter name?"""

from ..config import DEFAULT_OPENROUTER_MODEL


def is_jev_model(model):
    """Is this one of TypeSafe's Jev models?"""
    m = (model or "").strip().lower()
    return m.startswith("typesafe/") or m == "jev" or m.startswith("jev-")


def normalize_openrouter_model(model):
    """On OpenRouter, Jev models need a "typesafe/" name tag. Add it if it's missing."""
    m = (model or "").strip()
    if not m:
        return DEFAULT_OPENROUTER_MODEL
    low = m.lower()
    if low == "jev":
        return "typesafe/jev-latest"
    if low.startswith("jev-"):
        return f"typesafe/{m}"
    return m
