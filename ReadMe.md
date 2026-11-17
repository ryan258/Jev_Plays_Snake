# Jev Plays Snake
Docs 11-08-26 V1 (For questions or comments:  Stephen Witty switty@level500.com)  

### Project Overview:
This project tests how well TypeSafe's Jev decision model can play the classic game of Snake in real time. The project has two parts: a terminal Snake game, and a bot that plays the game from the outside. The bot never touches the game's code or memory. It only does what a person could do: it reads the screen through tmux and presses the arrow keys. On every move the bot turns the screen into a plain text grid and sends it to Jev, along with the rules and the three legal moves (never the reversal). By default Jev sees only the raw board, with no hints from the code, and picks a move (the optional `--guard` modes add hints and are "assisted" runs; see Command Line Options). The snake moves every 0.3 seconds, so any answer that arrives too late is dropped and the snake keeps going straight. Every move is logged (the board, Jev's answer, its confidence and response time, and the cost), and the screen of the best game is saved at the end of each run. A built-in path-finding player is also included, for comparison with a non-AI player. The software was written by Claude Code.

<img src="Pics/Best Game.png" width="500">

### Results (100 game run):
- Average score 9.3, best 27 (score = food eaten)
- Median Jev response time 125 ms, 99% of answers under 266 ms
- 1.3% of answers arrived too late to use
- 1 API error (a timeout) in 20,518 calls
- Total cost $1.10 for 100 games
- Jev's main weakness: it chases the food into its own body
- For comparison, the built-in path-finding player reached a score of 689 after more than 6 hours and was still going when stopped

### Reports / Documentation:
- [A story of 2 100-game Python runs](docs/a-story-of-2-100-game-python-runs.md) (comparing the 2026-11-07 TypeSafe direct run with the 2026-11-17 OpenRouter rerun)
- A presentation that covers the project can be found below:
- [Presentation Link](Presentations/Jev_Plays_Snake_V1_111226.pdf)
- Example run recorded:
- [Video](https://www.youtube.com/watch?v=d_FNSkt7MnM)

### Usage:
- The software is written in Python and runs in a terminal (originally tested on Ubuntu with Python 3.14 and tmux 3.6; also runs on macOS)
- Python 3 is required. It comes with Ubuntu; if it is missing: sudo apt install python3
- No extra Python packages are needed, only Python's standard library
- tmux is required: sudo apt install tmux
- Provide an API key via `.env` (copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY`), environment variables, or `jev_key.txt` in the directory the bot is started from
- Make the terminal at least 90 columns by 33 lines before starting, so the full 40 x 20 board fits
- Run the commands below from the `Source/` directory that holds `snake.py` and `snake_bot.py`
- Play the game yourself: `python3 snake.py` (arrow keys steer, P pauses, Q quits)
- Watch Jev play one game: `python3 snake_bot.py --games 1`
- Watch the built-in path-finding player instead (no API calls): `python3 snake_bot.py --player algorithm --games 1` (one game can run for hours)
- Press Q in the game to stop early
- Each run writes a log (.jsonl, plus a readable .txt) and the best game's screen (.html and .ans) to the `Outputs/` directory (configurable with `--log-dir`)
- The bot stops with a message if the TypeSafe or OpenRouter account runs out of credits, the API key is rejected, or 10 calls in a row fail

### Command Line Options:
snake.py (the game) has no command line options. Keys while playing:
- Arrow keys: steer
- P or Space: pause / resume
- R, Space, or Enter: play again after a game ends
- Q or Esc: quit

- snake_bot.py (the bot) opens a tmux session with the game on top and the bot's stats below, then plays:
- --player jev | openrouter | algorithm: who picks the moves (default from `SNAKE_PLAYER` in `.env`, or `openrouter` if `OPENROUTER_API_KEY` is set, else `jev`)
- --env-file FILE: load environment variables from FILE (default searches `./.env`, `Source/.env`, `../.env`)
- --guard off | safe | prompt | full: how much help the AI gets. Default `off` = raw board, the benchmark (the results above are raw-board). The other modes are ASSISTED runs and are not comparable with raw-board scores (logs are marked "ASSISTED"): `safe` filters 1-step wall/body collisions, `prompt` adds lookahead notes to the prompt without filtering, `full` also filters dead-end pockets. `safe` and `full` also short-circuit forced 1-option turns in 0 ms and fall back to the path-finder on must-turn frames
- --seed N: seed the random tie-breaks so a run can be repeated (the API's answers still vary)
- --compact-grid / --no-compact-grid: send compact unpadded grid + coordinate header to cut token count ~45% (default on when `--guard` is not `off`; `--guard off` always sends the classic board)
- --cot / --no-cot: on OpenRouter chat models, include a brief `"plan"` lookahead field before `"move"` in the JSON response (default on via `OPENROUTER_COT=1`)
- --games N: number of games to play, then stop (default 0 = keep playing until Q is pressed in the game)
- --key-file FILE: file holding the API key (default jev_key.txt in the directory the bot is started from)
- --model NAME: AI model to request (default `OPENROUTER_MODEL` or `JEV_MODEL` from `.env`, e.g. `google/gemini-2.5-flash-lite` or `jev-latest`)
- --log FILE: log file to append to (default a new file in `--log-dir` named for the player, date, and time, for example `jev_20261107_190304.jsonl`)
- --log-dir DIR: directory for logs and best game screens (default `Outputs/` at the repo root)
- --no-log: don't keep a log (the best game screen is still saved)
- --target PANE: play a game already running in tmux pane PANE instead of opening a new session
- --version: show the bot's version and exit
- -h, --help: show the options and exit
- Environment variables (or `.env`): `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, `OPENROUTER_COT`, `TYPESAFE_API_KEY`, `JEV_MODEL`, `SNAKE_PLAYER`, `SNAKE_GUARD`, `SNAKE_COMPACT_GRID`

### Code layout:
The bot is one program built from small modules in `Source/snakebot/`, stacked in layers. A module may only use modules in lower layers (a test checks this). Start it with `python3 snake_bot.py` from the Source directory.

| Layer | Modules | Job |
|---|---|---|
| 0 | config, geometry, prompts, tmuxio | settings, directions, the AI's rules text, talking to tmux |
| 1 | env, screen, pathfinding | .env and API key, reading the screen, path-finding |
| 2 | guard, players/wire, players/models | which moves the AI sees, message formats, model names |
| 3 | players/base, jev, openrouter, algorithm | the players |
| 4-5 | players (factory), report, runlog | picks the player, best-game picture, the log |
| 6-8 | runner, launcher, cli | the main loop, opening tmux, the command line |

To add a feature, put it in the lowest layer that makes sense. If the layer test fails, you reached up: move the shared piece down.

### Tests:
- No network, tmux, or API key needed. From the Source directory:
  - python3 -m unittest -v test_snake_bot (screen reading, tracker, path-finder, guard, .env loader, reply parsing, player errors)
  - python3 -m unittest -v test_architecture (the layer rule)

### Credit:
- This project was influenced by an earlier project: [typesafe-snake by sorrycc](https://github.com/sorrycc/typesafe-snake)
- No code was copied from it
