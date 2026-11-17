"""snakebot: a bot that plays snake.py from the outside, using tmux.

It is a "modular monolith": ONE program, built from small modules that each do one job.
Modules are stacked in layers. A module may only use modules in LOWER layers
(the test in test_architecture.py checks this), like a building where upper floors rest on lower ones.

  layer 0   config  geometry  prompts  tmuxio      (no dependencies inside the bot)
  layer 1   env  screen  pathfinding
  layer 2   guard  players.wire  players.models
  layer 3   players.base  players.jev  players.openrouter  players.algorithm
  layer 4   players (the factory)  report
  layer 5   runlog
  layer 6   runner          (the main loop)
  layer 7   launcher
  layer 8   cli             (the command line; the top)

Start it with:  python3 snake_bot.py
"""
