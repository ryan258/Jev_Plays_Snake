# A story of 2 100-game Python runs

Two runs of the same bot, the same game, and the same question: how well can TypeSafe's Jev
play Snake from a raw board, in real time, with nothing but the screen and the arrow keys?

- **Theirs:** the published run (2026-11-07), logged in `Game Logs/jev_20261107_190304_part*.jsonl`.
- **Ours:** a rerun on 2026-11-17, logged in `Outputs/openrouter_20261117_094608.jsonl`.

All numbers below were recomputed from the logs themselves, not copied from the ReadMe.

## The short version

Ours scored about **29% lower** (6.59 vs 9.28 average) and was **slightly slower**, but the
game worked the same way and it was cheaper per game. The gap is too big to be luck. What
caused it is **not yet known**, because five things changed at once.

## Side by side

| | Theirs | Ours |
|---|---|---|
| Games | 100 | 100 |
| **Average score** | **9.28** | **6.59** |
| Median score | 8 | 6 |
| Best score | 27 | 16 |
| Games scoring 10 or more | 42 | 20 |
| Score spread (std. deviation) | 5.62 | 3.28 |
| Games ended by own body / wall | 83 / 17 | 77 / 23 |
| Average moves per game | 205 | 107 |
| AI answers recorded | 20,518 | 10,710 |
| Late answers (dropped) | 266 (1.30%) | 271 (2.53%) |
| Median answer time | 125 ms | 153 ms |
| 99% of answers under | 265 ms | 335 ms |
| Failed API calls | 1 | 0 |
| Input tokens per call | 1,279 | 890 |
| Total cost | $1.10 | $0.40 |

## What the numbers say

**1. The score gap is real.** The difference is 2.7 points. With 100 games each, the margin of
error on that difference is about 0.65, so the gap is roughly four times larger than chance
would explain.

**2. The failure looks the same, but arrives sooner.** In both runs, most games end when Jev
steers into its own body (83% vs 77%), which is the weakness the original report names. Ours
ends in about half as many moves (107 vs 205), so Jev is dying earlier, not in a different way.
Ours also has no high-scoring tail: nothing above 16, versus a best of 27 and 42 games at 10
or more.

**3. Ours is slower, and past the step time at the top end.** The game moves every 300 ms. Our
99th-percentile answer took 335 ms, so more than 1% of answers can't land in time. Late
answers doubled (1.3% to 2.5%). A dropped answer means the snake keeps going straight.

**4. Ours is cheaper, for a reason we have not pinned down.** We sent about 30% fewer input
tokens per call (890 vs 1,279) and paid about 64% less in total (also fewer moves per game).
It is not the compact-grid option. With the guard off, the bot sends the classic space-padded
board in both runs (see the note below).

## What changed between the runs

| | Theirs | Ours |
|---|---|---|
| Model | `jev-latest` | `typesafe/jev-1.13-20260917` |
| Route | TypeSafe API direct (`api.typesafe.ai`) | OpenRouter (`/api/v1/systemone`) |
| Machine | Ubuntu, Python 3.14, tmux 3.6 | macOS, Python 3.15 |
| Bot code | the original v1 bot | later version, with the guard options and OpenRouter support (guard set to `off`) |
| Network path | unknown | home network, plus OpenRouter's hop |

Anything on this list could explain some or all of the gap. We cannot say which from these
two runs alone.

## What we can and cannot claim

**Established:**
- Our scores are lower, and not by chance.
- Our answers are slower and arrive late more often.
- Both runs fail the same way (running into itself), and neither run crashed or lost data.

**Not established (guesses):**
- *The newer model is worse at Snake.* Possible, since the model is the biggest change.
- *Latency costs score.* The extra 1.2% of late answers is too small to explain a 29% drop
  by itself, so this is probably not the main cause.
- *OpenRouter's route changes the answers.* Possible, but unmeasured.

## How to find the cause

Change one thing at a time. The cheapest, cleanest first test is the same bot, the same
machine, and the direct TypeSafe API with the original `jev-latest` model:

```bash
cd Source && python3 snake_bot.py --player jev --model jev-latest --guard off --games 100
```

(This needs a TypeSafe key in `TYPESAFE_API_KEY`.) That run isolates "model and route" from
"machine and code":

- If it scores near 9.3, the model or route is the cause, and the next test compares
  `jev-latest` and `jev-1.13` on the same route.
- If it still scores near 6.6, the cause is the machine, the network, or the later bot code.

Every 100-game run costs under $1.50.

## A note on one thing we got wrong along the way

While planning a follow-up run, we suggested comparing `--no-compact-grid` against our run.
That test would have changed nothing: the bot turns off the compact board whenever the guard is
`off`. Both of these runs used the classic board. The `compact_grid: true` line in our log
recorded what was *asked for*, not what was sent, so it was misleading on its own (subsequently
fixed in `Source/snakebot/runlog.py` so logs now record the effective value).

## Footnote: how our run got set up

Our first attempts failed for setup reasons, not Snake reasons: a model name that does not
exist on OpenRouter (`typesafe/jev-latest`), then a general-purpose model
(`google/gemini-2.5-flash-lite`) whose answers were all too slow (median 392 ms against a
300 ms step, score 0). The real Jev model on OpenRouter is a different ID, and with it the
run behaved normally. A 10-game trial (average 5.6) predicted the 100-game result (6.59)
reasonably well.
