"""The AI players, and a factory that picks the right one.

Three players can choose moves:
  jev         asks TypeSafe's Jev model
  openrouter  asks a model on OpenRouter
  algorithm   a built-in path-finder (no internet)
"""

from .algorithm import AlgorithmPlayer
from .jev import JevPlayer
from .openrouter import OpenRouterPlayer


def make_player(args):
    """Build the player that the command-line options ask for."""
    if args.player == "openrouter":
        return OpenRouterPlayer(args.key_file, args.model, guard=args.guard,
                                compact_grid=args.compact_grid, cot=args.cot)
    if args.player == "jev":
        return JevPlayer(args.key_file, args.model, guard=args.guard, compact_grid=args.compact_grid)
    return AlgorithmPlayer()
