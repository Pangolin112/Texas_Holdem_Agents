# Texas Hold'em Agents ♠♥♦♣

No-Limit Texas Hold'em: **you** against a table of **OpenAI-powered
opponents**, each with its own personality. They decide what to do from their
hole cards, the board, the pot, everyone's stacks, the full betting history,
past hands at the table — and whatever trash talk you throw at them.

Play it **two ways**, both driven by the *same* game engine and the same AI
brains:

| Version | Run | Look |
|---|---|---|
| **Terminal** | `python main.py` | text table in your console |
| **Web** | `python webapp.py` | 2D table in the browser — animated cards, seats, chips, speech bubbles |

> **One engine, many front-ends.** All the poker logic (rules, betting,
> side pots, hand evaluation, the LLM/heuristic brains) lives once in the
> `holdem/` package. The terminal and the web app are just two *views* onto
> it, so a feature added to the engine appears in both at once. A future 3D
> client would plug in the same way. **When you add a new feature, wire it
> into every front-end.** See [Architecture](#architecture-shared-core) below.

## Setup

```bash
pip install -r requirements.txt
copy .env.example .env      # then paste your OpenAI API key into .env
```

(Or set the `OPENAI_API_KEY` environment variable instead of using `.env`.
Both versions run without a key too — they fall back to offline bot logic.)

## Play — terminal

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
| `--show-cards` | peek mode: also open up **folded** players' cards in the end-of-hand review |
| `--no-odds` | don't show your live hand strength and win odds |
| `--lang zh` | the agents speak Chinese — table talk, reactions, explanations (default `en`) |

## Play — web (2D table)

```bash
python webapp.py            # then open http://127.0.0.1:8000 (opens automatically)
python webapp.py --port 8080 --no-browser
```

A local, dependency-free server (Python standard library only — no Flask, no
npm) hosts a browser front-end with a green-felt 2D table: seats around an
oval, animated dealt cards, community board and pot in the middle, the dealer
button, per-seat stacks/bets and a "thinking…" glow while an AI decides, and
speech bubbles when the table talks. A **setup screen** lets you pick your
name, the number of opponents, stacks, blinds, model, and offline/peek/odds
modes — every option the terminal has. Click **Fold / Check-Call / Raise** (with
a slider and ½·¾·pot shortcuts) **/ All-in**, type in the **Say** box to chat,
and between hands **buy chips** or deal the next one. A live **table feed** on
the right logs every action, showdown and remark, and a panel above it tracks
[your hand and win odds](#your-live-hand--win-odds) in real time. An
[autopilot](#autopilot--commit-before-your-turn) row lets you commit to a move
before the turn even reaches you, and when the hand ends you get the
[review](#end-of-hand-review) of every seat's cards.

Under the hood the real `holdem` engine runs in a background thread; each game
event is streamed to the browser over Server-Sent Events, and your clicks are
sent back as the very same commands the terminal accepts (`f`, `c`, `r 120`,
`a`, `say …`, `buy 200`). No poker logic is duplicated in JavaScript.

**Language — English / 中文.** Pick the table language on the setup screen (or
toggle 中文/EN in the top bar; it's remembered). The whole UI switches, the
engine's action/pot/hand-name lines are shown translated, and — set at game
start — the **agents themselves speak the chosen language**: their table talk,
reactions, and "why did you do that" explanations come back in Chinese or
English. (The engine still runs in English internally; the terminal version
has the same agent-language switch via `--lang zh`.)

**Voice.** Click the **🎤** button and just say your move — *"fold"*, *"call"*,
*"raise to 200"*, *"all in"*, or in Chinese *“弃牌”“跟注”“加注到200”“全下”* —
and it plays; anything else you say is sent as table talk, exactly like the Say
box (*"next hand"* / *“下一手”* deals between hands, *"buy 200"* / *“买200”*
tops up). Speech input uses the browser's Web Speech API (Chrome/Edge over
HTTPS or localhost; the button hides itself where unsupported).

With **🔊** on, the agents talk back out loud in **natural voices**: their
lines are spoken through **OpenAI's TTS** (`gpt-4o-mini-tts`), each personality
with its own voice and delivery — Mike booms, Sarah deadpans, Ray barely
bothers. Only the words are spoken, never the speaker's name. The audio is
generated server-side (`/api/tts`), so the API key stays on the server; TTS
audio, like the table's brains, spends the host's OpenAI credits. Offline
games (or any TTS hiccup) fall back to the browser's built-in voice
automatically.

**Talk whenever you want.** The Say box and the mic work at *any* moment — not
just on your turn. Speak while an opponent is still thinking and the table
hears you immediately: the same selective-reply rules apply (name someone and
they answer, question a move and you get the real reasoning, a table-wide
remark draws at most one voice). Under the hood the web app delivers chat on a
separate thread (`/api/say`), so a slow model decision never blocks the
conversation.

## Play — online (share a link)

Deploy `webapp.py` to a host (Render's free tier via `render.yaml`, or any
Docker host via the included `Dockerfile`) with your `OPENAI_API_KEY` stored as
a server secret, and the service URL — `https://<your-app>.onrender.com` — is a
link **anyone can open and play**, LLM opponents included. The server accepts
**several games at once** (one per visitor, `MAX_GAMES` cap), honors `$PORT`,
has a `/healthz` check, and offers an optional `ACCESS_CODE` gate.

> ⚠️ With your key on the server, every visitor's game spends **your** OpenAI
> credits. Set an account spending limit, and see the access-code / offline
> options in the deploy guide.

**Step-by-step (~5 min):** see **[DEPLOY.md](DEPLOY.md)**.

## At the table

On your turn:

| Command | Action |
|---|---|
| `f` | fold |
| `c` (or Enter when free) | check / call |
| `r 120` | raise **to** 120 total for this street |
| `a` | all-in |
| `ff` / `cc` / `cs` | autopilot: fold this hand / call everything / call this street |
| `x` | autopilot off — hand the controls back |
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

**Topping up.** Between hands you can reload before the next deal: type
`buy <n>` to add chips to your stack — up to one starting stack per hand — and
each AI decides for itself whether to do the same. When a bot is sitting below
a full buy-in it genuinely weighs a top-up: its own model looks at its stack,
its tab, how it's running and who's ahead, and reloads (or passes) in
character — offline bots go on instinct instead. Bought chips come from the
house and go on your tab just like a rebuy, so your net (stack − debt) is
unchanged — it's more ammunition on the table, not profit.

## Reading the hand

### Your live hand + win odds

While you're in a hand, the game keeps a running read on your seat: **the best
five cards you hold right now**, updated the moment a card lands — and, for
every hand you could still *get to*, how often you make it and how often that
actually wins. It runs from the deal, **preflop included**, where there's no
five-card hand yet so it names what you're actually holding instead (*Pocket
Nines*, *Ace-King suited*) and prices that:

```
 ── your odds ──   vs 3 live · 10112 hands simulated
   holding: Seven-Six offsuit   6♣ 7♦
   Straight         make 10%   win  7%   █
   Two Pair         make 22%   win  6%   █
   Pair             make 43%   win  3%   █
   ...
   TOTAL            you win 21%   (win 20% · tie 3%)
```

Once there's a board it's a real hand again:

```
 ── your odds ──   vs 1 live · 15104 hands simulated
   now: a Pair of Nines   9♥ 9♠ K♦ 7♣ 4♠
   Flush            make 35%   win 34%   ███████
   Two Pair         make  7%   win  5%   █
   Pair             make 33%   win 15%   ███
   High Card        make 23%   win  3%
   TOTAL            you win 57%   (win 55% · tie 4%)
```

Read it as a decomposition rather than nine unrelated numbers: **the win column
sums to the total**. When you're drawing at several things at once — a flush,
trips, a straight — this is what tells you which of them is actually carrying
your equity and where you really stand.

The numbers come from a Monte-Carlo simulation (`holdem/odds.py`): every rollout
deals the missing board and each live opponent's hole cards from the genuinely
unknown cards, ranks everyone, and books the result under the category you ended
with. Ties are booked as fractional wins (1/N for an N-way chop), so the total is
the equity you'd actually realize. It's bounded by wall-clock rather than a fixed
sample count — a few thousand rollouts per spot, accurate to well under a percent.
Only *your* seat gets this; the agents reason from their own view, and handing
them a solver would make them something else entirely. Turn it off with
`--no-odds` (or the setup checkbox).

### Autopilot — commit before your turn

Decide early and stop waiting on the table:

| | |
|---|---|
| **Fold in advance** (预先弃牌) | you're done with this hand — it checks while checking is free, and folds the moment someone bets |
| **Call everything** (默认全跟) | call whatever comes, all hand |
| **Call this street** (跟当前轮次) | call for the rest of this street only, then the controls come back |

In the browser these are buttons you can hit **while someone else is still
thinking** — the point of folding in advance. The commitment covers the hand it
was made in and clears on the next deal; click the armed button again to take
the controls back.

### End-of-hand review

When a hand ends, every seat is laid out **strongest first** with the formula it
arrived at and the exact five cards that played (the ones out of their own hand
ringed in gold):

```
 ── hand #2 · final hands, strongest first ──
   board: 9♠ 7♦ 3♣ 4♦ 8♦
   #1 Linda    9♥ 10♥  a Pair of Nines     9♥ 10♥ 9♠ 7♦ 8♦   +2091
   #2 Sarah    9♣ 6♣   a Pair of Nines     9♣ 6♣ 9♠ 7♦ 8♦
   #3 You      2♣ 6♥   High Card, Nine     6♥ 9♠ 7♦ 4♦ 8♦    folded
   Ray         (mucked — cards not shown)
```

Card strength across the table reads at a glance — including whether the hand
you folded was the best one. Your own cards are always there, and so is anyone
who went to showdown. **Mucked hands stay mucked**: a seat that folded without
showing keeps its cards, so this runs after every hand without leaking anything
the table didn't already see. Run with `--show-cards` (**peek mode**, or the
setup checkbox) to open the folders up too — a study view for seeing what the
AIs were actually holding and whether a bluff was real. Nothing is ever revealed
mid-hand.

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

## Architecture (shared core)

One engine, swappable front-ends:

```
holdem/                shared core — no front-end code
  cards.py             deck + cards
  evaluator.py         best 5-card hand, side-pot ranking, fast 7-card ranker
  odds.py              Monte-Carlo equity + per-category chances (your seat only)
  brains.py            LLM + heuristic decision-making (the personalities)
  players.py           human + AI seats (incl. the autopilot commitments)
  game.py              the No-Limit engine (betting, pots, showdowns, chat)
  ui.py                presentation layer + a pluggable **Sink**

main.py                terminal front-end   (default: prints via ui.py)
webapp.py              web front-end         (installs a WebSink; SSE + browser)
static/                the 2D table (index.html, style.css, app.js)
```

The engine only ever talks to the outside world through `holdem/ui.py`. By
default those calls print to the terminal. A front-end can instead install a
`ui.Sink` on the game thread (`ui.set_sink`): every event is then handed to the
sink as structured data, and player input is read back through it. `webapp.py`'s
`WebSink` turns those events into JSON for the browser and feeds clicks back in
as terminal-style commands. The terminal uses no sink at all, so its behaviour
is byte-for-byte unchanged.

**Adding a feature:** put the logic in `holdem/` and emit it through a `ui.py`
function. The terminal renders it by printing; give the `Sink` a matching
method and have the web front-end (and any future 3D client) render it too, so
all versions stay in step.

## Tests

```bash
python test_game.py
```

Covers the hand evaluator, betting engine, side-pot math, and runs hundreds
of simulated hands checking that chips are never created or destroyed.

Two things worth knowing about, since they're easy to get subtly and silently
wrong:

- **The fast ranker.** `evaluator.rank_cards` reads a hand off rank/suit counts
  instead of trying all 21 five-card combinations (~19× faster, which is what
  makes the odds simulation affordable). It's only allowed to exist because the
  suite checks it against the obvious brute-force version over thousands of
  random 5/6/7-card deals — plus the shapes a counting evaluator trips on: the
  steel wheel, two trips making a full house, three pairs, six of a suit.
- **The odds.** Pinned to published equities (aces 85.3% heads-up, suited AK
  67.0%, 7-2 offsuit 34.6%) and to closed-form combinatorics (a flopped flush
  draw completes 1 − (38/47)(37/46) = 35.0%), with the invariants checked too:
  make% covers every runout exactly once, and the per-category win column sums
  to total equity.
