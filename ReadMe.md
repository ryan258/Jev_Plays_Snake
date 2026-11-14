# Jev Plays Snake
Docs 11-08-26 V1 (For questions or comments:  Stephen Witty switty@level500.com)  

### Project Overview:
This project tests how well TypeSafe's Jev decision model can play the classic game of Snake in real time. The project has two parts: a terminal Snake game, and a bot that plays the game from the outside. The bot never touches the game's code or memory. It only does what a person could do: it reads the screen through tmux and presses the arrow keys. On every move the bot turns the screen into a plain text grid and sends it to Jev, along with the rules and the three legal moves (never the reversal). Jev sees only the raw board, with no hints from the code, and picks a move. The snake moves every 0.3 seconds, so any answer that arrives too late is dropped and the snake keeps going straight. Every move is logged (the board, Jev's answer, its confidence and response time, and the cost), and the screen of the best game is saved at the end of each run. A built-in path-finding player is also included, for comparison with a non-AI player. The software was written by Claude Code.

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
- A presentation that covers the project can be found below:
- [Presentation Link](presentation/Jev_Plays_Snake_V1_111226.pdf)
- Example run recorded:
- [Video](https://www.youtube.com/watch?v=d_FNSkt7MnM)

### Usage:
- The software is written in Python and runs in a Linux terminal (tested on Ubuntu with Python 3.14 and tmux 3.6)
- Python 3 is required. It comes with Ubuntu; if it is missing: sudo apt install python3
- No extra Python packages are needed, only Python's standard library
- tmux is required: sudo apt install tmux
- Provide a TypeSafe API key, either in a file named jev_key.txt in the directory the bot is started from, or in the TYPESAFE_API_KEY environment variable
- Make the terminal at least 90 columns by 33 lines before starting, so the full 40 x 20 board fits
- Run the commands below from the directory that holds snake.py and snake_bot.py
- Play the game yourself: python3 snake.py (arrow keys steer, P pauses, Q quits)
- Watch Jev play one game: python3 snake_bot.py --games 1
- Watch the built-in path-finding player instead (no API calls): python3 snake_bot.py --player algorithm --games 1 (one game can run for hours)
- Press Q in the game to stop early
- Each run writes a log (.jsonl, plus a readable .txt) and the best game's screen (.html and .ans) to the directory the bot is started from
- The bot stops with a message if the TypeSafe account runs out of credits, the API key is rejected, or 10 calls in a row fail

### Command Line Options:
snake.py (the game) has no command line options. Keys while playing:
- Arrow keys: steer
- P or Space: pause / resume
- R, Space, or Enter: play again after a game ends
- Q or Esc: quit

snake_bot.py (the bot) opens a tmux session with the game on top and the bot's stats below, then plays:
- --player jev | algorithm: who picks the moves (default jev)
- --games N: number of games to play, then stop (default 0 = keep playing until Q is pressed in the game)
- --key-file FILE: file holding the TypeSafe API key (default jev_key.txt in the directory the bot is started from)
- --model NAME: Jev model to request (default jev-latest)
- --log FILE: log file to append to (default a new file named for the player, date, and time, for example jev_20261107_190304.jsonl)
- --log-dir DIR: directory for logs and best game screens (default the directory the bot is started from)
- --no-log: don't keep a log (the best game screen is still saved)
- --target PANE: play a game already running in tmux pane PANE instead of opening a new session
- --version: show the bot's version and exit
- -h, --help: show the options and exit
- Environment variable TYPESAFE_API_KEY: the API key, used instead of the key file when set

### Credit:
- This project was influenced by an earlier project: [typesafe-snake by sorrycc](https://github.com/sorrycc/typesafe-snake)
- No code was copied from it
