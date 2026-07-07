# Texas Hold'em Agents ♠♥♦♣

No-Limit Texas Hold'em in your terminal: **you** against a table of
**OpenAI-powered opponents**, each with its own personality. They decide what
to do from their hole cards, the board, the pot, everyone's stacks, the full
betting history, past hands at the table — and whatever trash talk you throw
at them.

## Setup

```bash
pip install -r requirements.txt
copy .env.example .env      # then paste your OpenAI API key into .env
```

(Or set the `OPENAI_API_KEY` environment variable instead of using `.env`.)

## Play

```bash
python main.py
```

Options:

| Flag | Meaning |
|---|---|
| `--opponents N` | number of AI opponents, 1–7 (default 5) |
| `--stack N` | starting stack (default 1000) |
| `--sb N` / `--bb N` | blinds (default 10/20) |
| `--model NAME` | OpenAI model (default `gpt-4o-mini`, or `$OPENAI_MODEL`) |
| `--offline` | no API — opponents use built-in bot logic |
| `--fast` | skip the dramatic pauses |
| `--seed N` | reproducible shuffles |

## At the table

On your turn:

| Command | Action |
|---|---|
| `f` | fold |
| `c` (or Enter when free) | check / call |
| `r 120` | raise **to** 120 total for this street |
| `a` | all-in |
| `say nice try, robot` | table talk — the AIs hear it and react |
| `h` | help, `q` — leave the table |

Full no-limit rules: blinds, min-raise tracking, all-ins, split pots and
side pots. Busted AIs leave the table (with parting words); if you bust,
you'll be offered a rebuy.

## The opponents

Tex (maniac cowboy), Ivy (icy math PhD), Rusty (superstitious calling
station), Nova (chaotic hacker), The Professor (GTO lecturer), Lucky Lin
(fate-trusting gambler) and Dmitri (silent rock). Each hand, every AI decision
is one API call with only public information plus that AI's own cards — they
bluff, needle you, and hold grudges across hands.

If the API is unreachable mid-game, that opponent quietly falls back to
built-in instincts, so the game never crashes.

## Fairness

The deck is shuffled with `random.SystemRandom` — cryptographically secure
OS entropy — so every deal is unpredictable and unbiasable, and cards are
dealt one at a time around the table like a live dealer. No seat (human or
AI) is favored, and the AIs are never shown anyone's hole cards but their
own. `--seed` switches to a reproducible shuffle for testing only, and the
game tells you at startup which mode is active. The test suite includes a
20,000-deal distribution check confirming no seat gets better cards.

**Cost note:** with `gpt-4o-mini` a full evening of poker costs pennies; a
6-player hand makes roughly 15–25 small API calls.

## Tests

```bash
python test_game.py
```

Covers the hand evaluator, betting engine, side-pot math, and runs hundreds
of simulated hands checking that chips are never created or destroyed.
