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
| `--model NAME` | OpenAI model (default `gpt-5-mini`, or `$OPENAI_MODEL`) |
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
| `say nice try, robot` | chat with the table — the AIs hear you and answer back |
| `h` | help, `q` — leave the table |

You can chat during your turn or between hands; agents named in your message
always answer, and the whole conversation feeds into everyone's decisions.

Full no-limit rules: blinds, min-raise tracking, all-ins, split pots and
side pots. Nobody is ever eliminated: whoever goes broke (you included) is
automatically restaked by the house, and the loan is tracked on their tab —
standings show stack, debt, and net.

## The opponents

Tex (maniac cowboy), Ivy (icy math PhD), Rusty (superstitious calling
station), Nova (chaotic hacker), The Professor (GTO lecturer), Lucky Lin
(fate-trusting gambler) and Dmitri (silent rock). Each hand, every AI decision
is one API call with only public information plus that AI's own cards — the
prompt spells out their made hand and pot odds, and demands disciplined play:
big bets need real hands. They bluff, needle you, answer your table talk, and
hold grudges (and debts) across hands.

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

**Cost note:** a 6-player hand makes roughly 15–25 small API calls (plus one
per AI reply when you chat). `gpt-5-mini` keeps an evening of poker cheap;
`--model gpt-4o-mini` is cheaper but plays worse, `--model gpt-5` is sharper.

## Tests

```bash
python test_game.py
```

Covers the hand evaluator, betting engine, side-pot math, and runs hundreds
of simulated hands checking that chips are never created or destroyed.
