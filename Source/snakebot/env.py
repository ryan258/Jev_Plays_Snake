"""Secrets and settings from the environment: the .env file and the API key.

The key is only ever read here. It is never printed or logged."""

import os
import re
import sys
from pathlib import Path

from .config import HERE


def load_dotenv(env_file=None):
    """Read KEY=VALUE lines from a .env file into the environment.
    Variables that are already set win. Returns the file used, or None."""
    candidates = ([Path(env_file).expanduser()] if env_file
                  else [Path.cwd() / ".env", HERE / ".env", HERE.parent / ".env"])
    for path in candidates:
        try:
            if not path.is_file():
                continue
            for raw in path.read_text().splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, value = (part.strip() for part in line.split("=", 1))
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]  # "quoted" values are kept exactly
                else:  # a comment starts at " #". A "#" with no space before it is part of the value.
                    value = re.split(r"\s#", value, maxsplit=1)[0].strip()
                if key and key not in os.environ:
                    os.environ[key] = value
            return path.resolve()
        except OSError:
            continue
    return None


def read_key_file(key_file):
    """The key stored in a file, or "" if the file is missing or still holds the placeholder."""
    try:
        key = Path(key_file).expanduser().read_text().strip()
    except OSError:
        return ""
    return "" if key.startswith("apikey_XXXX") else key


def load_api_key(key_file, player="jev"):
    """Find the secret API key: first in the environment (.env), then in the key file."""
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if or_key == "your_openrouter_api_key_here":  # the placeholder from .env.example
        or_key = ""
    ts_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if player == "openrouter":
        key = or_key or read_key_file(key_file)
        if not key:
            sys.exit("No OpenRouter API key: set OPENROUTER_API_KEY in .env (or the environment)")
        return key
    key = ts_key or or_key or read_key_file(key_file)
    if not key:
        sys.exit(f"No API key: set OPENROUTER_API_KEY or TYPESAFE_API_KEY in .env, or put the key in {key_file}")
    return key


def key_env_var(player):
    """Which environment variable holds the API key this player will use?"""
    if player == "openrouter":
        return "OPENROUTER_API_KEY"
    if os.environ.get("TYPESAFE_API_KEY", "").strip() or not os.environ.get("OPENROUTER_API_KEY", "").strip():
        return "TYPESAFE_API_KEY"
    return "OPENROUTER_API_KEY"  # Jev reached through OpenRouter
