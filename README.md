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
| `--model NAME` | preferred OpenAI model (default `gpt-5.2`, or `$OPENAI_MODEL`; auto-falls back if unavailable) |
| `--offline` | no API — opponents use built-in bot logic |
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

You can chat during your turn or between hands, and the game understands who
you're talking to: name someone ("Sarah, nice bluff") and they answer; say
"you" with no name and it resolves to whoever you're replying to (shown as
"(to Sarah)" so you can see it understood); group words like "everyone" reach
the whole table. To keep the pace up, each remark draws at most one reply and
replies don't chain, so the table stays snappy instead of erupting into a
round of back-and-forth. Agents also react to moves once in a while — a big
all-in might get a word, most hands pass quietly. The addressed conversation
still feeds into everyone's decisions.

**Ask why.** Idle needling gets idle banter, but if you actually *question a
move* — "Sarah, why did you raise there?", "Dave, explain that call" — the
game recognizes it and that player walks you through the real reasoning: the
board, pot odds and price, position, stacks, and what they were representing.
(While a hand is still live they may keep their exact cards to themselves, but
the logic they give is genuine, not a brush-off.)

Full no-limit rules: blinds, min-raise tracking, all-ins, split pots and
side pots. Nobody is ever eliminated: whoever goes broke (you included) is
automatically restaked by the house, and the loan is tracked on their tab —
standings show stack, debt, and net.

## The opponents

Seven regulars from a weekly home game: Mike (loose-aggressive retired
firefighter), Sarah (tight accountant), Emma (med student who can't fold),
Dave (blunt contractor), Linda (patient retired math teacher), Frank (barber
riding imaginary heaters) and Ray (quiet trucker). They talk like normal
people at a card table — short, casual, reacting to what actually happened —
not like scripted characters. As far as they know, everyone at the table
(you included) is just another person; nobody is told a human or a bot is
playing. Each hand, every decision is one API call with only public
information plus that player's own cards — the prompt spells out their made
hand and pot odds. They play a loose home-game style: hard to bluff off a
pot, happy to call with a piece or a draw, and only shoving all-in with a
real hand — but they still fold trash to big pressure. They bluff, needle
you, answer your table talk, and hold grudges (and debts) across hands.

Their talk is bound to their chips: a player can lie all day about *what
they hold* ("I flopped a set"), but if they announce *what they're doing* —
"I fold", "I'm all in" — the actual move is forced to match. So a spoken
call is a call and a spoken shove is a shove; only the card-strength story
can be a bluff.

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
per AI reply when you chat, or one deeper call when you ask a seat to explain
a move). The default `gpt-5.2` plays the sharpest; `--model gpt-5-mini` or
`--model gpt-4o-mini` are cheaper if you'd rather spend less.

## Tests

```bash
python test_game.py
```

Covers the hand evaluator, betting engine, side-pot math, and runs hundreds
of simulated hands checking that chips are never created or destroyed.
