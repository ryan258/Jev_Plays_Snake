"""Talking to tmux: take a "photo" of the screen, and press a key.

This is the ONLY place the bot touches the game. Everything else works on the photo."""

import subprocess


def tmux(*args, check=True):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)


def capture(target):
    """Take a "photo" of the pane as text with colour codes. None if the pane is gone."""
    r = tmux("capture-pane", "-p", "-e", "-t", target, check=False)
    return r.stdout if r.returncode == 0 else None


def press(target, key):
    tmux("send-keys", "-t", target, key, check=False)
