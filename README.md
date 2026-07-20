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
| `--no-coach` | play without the AI coach reading the table for you |
| `--no-fast-forward` | after you fold, let the AIs keep thinking at full depth instead of finishing the hand on instinct |
| `--lang zh` | the agents speak Chinese — table talk, reactions, explanations (default `en`) |

**Fast-forward.** Once you fold, the rest of the hand is bots settling a pot
you have no stake in — so by default the table hurries: LLM seats finish the
hand on their built-in instincts (same personality weights, zero model calls),
spontaneous commentary goes quiet, and a bot's one-liner can't solicit a
model-priced reply. Measured on the live API: the remainder of a hand that
would have taken ~20-30 seconds of thinking completes in under two. Your own
chat still gets answered while you watch, and the moment the next hand deals
you in, full-depth thinking resumes. Deliberately **not** triggered when
you're all-in — you still have the pot at stake, and whether the others fold
or fight decides how much of it you win, so those moves keep their real
thinking. Turn it off with `--no-fast-forward` or the setup checkbox.

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
| `ai` | do what the coach just told you to do |
| `aa` | autopilot: follow the coach for the rest of this street |
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
game recognizes it and that player answers you directly. Once the hand is
over, you get the real reasoning: the board, pot odds and price, position,
stacks, and what they were representing. But question them *while the hand is
still live* and you're playing poker, not attending a seminar — they owe you
nothing mid-hand, and may deflect, give away as little as they like, or sell
you exactly the story they want you to believe.

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

> **"Aren't those overlapping? You can't just add draws together."** Right — and
> it doesn't. This is the classic outs-counting trap: with 9♠8♠ on 7♠6♥2♠K♦ you
> have 9 spades for the flush and 8 cards for the straight, and *17 outs* is
> wrong, because 5♠ and 10♠ do both. The real answer is 15.
>
> Nothing here counts outs. Each simulated runout is classified by the **one
> final hand it actually ends with** — a 5♠ river makes both a flush and a
> straight, so it books as a flush, once, and never as a straight. The rows are
> mutually exclusive by construction, which is precisely *why* they add up. In
> that spot the table reports Flush 18.9% + Straight 13.0% = 31.8%, not the
> naive 38.6%. Checked against a brute-force enumeration of all 45,540
> (river × opponent hand) combinations: **47.17% exact vs 46.78% simulated**,
> with the make column summing to 1.0 and the win column to the equity, exactly.
> One consequence worth knowing: *Straight 13%* means "ends up a straight and
> nothing better" — the runouts where you make a straight *and* a flush are
> counted under Flush.

The numbers come from a Monte-Carlo simulation (`holdem/odds.py`): every rollout
deals the missing board and each live opponent's hole cards from the genuinely
unknown cards, ranks everyone, and books the result under the category you ended
with. Ties are booked as fractional wins (1/N for an N-way chop), so the total is
the equity you'd actually realize. It's bounded by wall-clock rather than a fixed
sample count — a few thousand rollouts per spot, accurate to well under a percent.
Only *your* seat gets this; the agents reason from their own view, and handing
them a solver would make them something else entirely. Turn it off with
`--no-odds` (or the setup checkbox).

### The coach

A second AI stands behind your chair. It doesn't play — it reads the table and
tells you what to do, and then it has to live with it.

```
 ── the coach ──   72% sure · read the model
   Mike       ████████   bet every street — big pair or a set, not a flush
   Emma       ████       along for the ride, probably a draw
   you win 62% (55% after the read) · the price needs 30%
   RAISE to 620  You have the nuts on a wet board — make him pay for the river.
   'ai' to do it · 'aa' to follow the coach all street
```

**It reads opponents from their betting, never from their cards** (`ranges.py`).
It is not allowed to see anyone's hole cards, and doesn't. Instead it starts
from every hand each opponent could still hold and lets each thing they did move
the odds on each of them:

```
P(hand | what they did)  ∝  P(hand) × ∏ P(each action | that hand)
```

The prior is flat over every two-card combination not already accounted for —
the board, and **your own cards**, which is why holding the A♠ genuinely does
make his flush less likely. Strength is exact, not estimated: with the board
known, "how good is this holding" is just where it ranks among all the others,
which is a count. Each action is judged against the board *as it was at the
time* — a bet on the flop says something about a flop hand, not a river one.

The only opinion in the file is the likelihood, and it encodes one idea instead
of a pile of thresholds: **betting is polarized** (strong hands *and* hands with
nothing, since those can't win any other way), **calling is condensed** (good,
not good enough to raise). Run it over every holding and the posterior *is* the
range:

| he... | mean | bluff | his range |
|---|---|---|---|
| has done nothing | 50% | — | air 30% · weak 26% · medium 25% · strong 20% |
| checked | 45% | — | strong drops to 9% |
| called a bet | 59% | — | **medium 48%** — condensed, as theory says |
| bet ¼ pot | 62% | **28%** | strong 44% · medium 24% · air 28% |
| bet pot | 61% | **32%** | strong 48% · medium 18% · air 32% |
| shoved 4x pot | 59% | **37%** | strong 51% · **medium 10%** · air 37% |
| bet flop, barrelled turn | 71% | **24%** | strong 67% |

Read the bottom rows: as the bet grows the **medium hands drain out** (24% → 10%)
and *both* ends grow. That's what polarized means, and it's why the bluff number
rises with bet size — landing near where balanced play says it should (about a
third of a pot-sized bet). Fire twice, though, and you're just strong.

**Bluff % is only quoted for someone who is betting** — you cannot bluff by
calling — and it's the posterior weight sitting on hands that can't currently
beat anything. Draws are counted separately as semi-bluffs.

**Then equity gets re-measured against those ranges, not against strangers.**
The panel's headline number is your equity against *random* hands, which is the
right baseline and the wrong opponent. Given a posterior for each live seat, the
coach re-runs the same simulation dealing them hands **drawn from their ranges**
(`odds.hand_odds(..., ranges=...)`) — a real number, not a fudge factor. That
second number is what meets the pot odds:

```
you win 47% vs random · 38% vs their range · the price needs 30%   ->  CALL
```

Call when it beats the price, fold when it doesn't, raise when you're far enough
ahead to get paid.

**The panel wears the spot's color.** White → green → blue → red → purple, each
step more dangerous, computed from how far your equity against their ranges
sits from the price (`danger_level` in `advisor.py`) — so a glance tells you
whether this is a "take the free card" street or a "get out now" one. While the
coach re-reads the table the panel pulses a neutral "analyzing" tone; the
moment the new advice lands, the tint snaps in — that flip is the "analysis
done" signal. When checking is free the scale caps at blue: a weak hand with
nothing to pay is weak, not in danger, and a panel that cries wolf on every bad
flop teaches you to ignore it. The terminal colors its coach banner on the same
scale, and the felt itself drifts hue with the street (flop cooler, turn
warmer, river deepest) so you can feel where the hand is peripherally.

**One click to follow it.** The **Follow the coach** button says what it will
do — *Follow the coach · Raise to 620* — so it's never a leap of faith. Or arm
**本轮跟随 AI** to let it play the rest of the street for you. The engine ships
the command *with* the advice, so the button, the autopilot and the terminal
can't drift into following it three different ways.

**It owns the result.** When the hand ends the coach is told what actually
happened and whether you listened, and has to say so:

| | |
|---|---|
| you listened, it worked | *"What did I say."* |
| you ignored it, it cost you | *"我不是早就说了别想了直接弃牌吗，这下白送180。"* |
| you listened and it cost you | *"...Right. Forget I said anything."* |
| you ignored it and won | it eats that one too |
| nothing was shown down | *"Nothing to learn from that one."* |

That last row matters: it judges itself **only on hands the table actually
showed** (plus everything, in peek mode). If everyone folded, nobody knows what
would have happened — so it doesn't get to claim it was right, and it can't leak
what the mucked cards were. And if you go your own way mid-hand, it says
something about that too, right then.

**The debrief.** After the one-liner comes the whole hand, decision by decision
— what it advised, what you did, and a **process grade** computed from the
numbers each move was made against:

```
 ── the coach's debrief ──   this hand -60
   PREFLOP  told FOLD    · you: calls 20    loose call — priced out
   FLOP     told CHECK   · you: checks      ok
   TURN     told FOLD    · you: calls 40    loose call — priced out
   coach: "You paid for cards the price didn't justify. That's where the chips go."
   session: 8 hands · followed 11/17 · net +120 listening, -380 your own way · loose calls ×4
```

Process, never results: a correct call that lost money is still graded fine,
and a hand you *won* while checking a monster three streets still reads
*missed value ×3* — which is exactly what a coach is for. Four grades exist:
**scared fold** (the price was right), **loose call** (priced out), **raised
while behind**, and **missed value**; marginal spots take no grade at all,
because a debrief that nitpicks every coin flip teaches you to close the panel.

Underneath sits the **session ledger** — 一直以来的打法: hands, how often you
follow the advice, your net on hands where you listened versus hands where you
went your own way, and your recurring leaks by name. The coach uses it to talk
about *habits*, not moments ("这已经是今晚第四次松跟,老毛病得改了"), and it
only names a habit once there's real evidence — under five hands, a pattern is
a coincidence. With the API the debrief is written prose in character; offline
(or on any API failure) it's built from the same grades with canned lines.
Trivial hands — one advised decision, small pot — never spend a model call.

In the browser the debrief sits inside the end-of-hand overlay, under the
result table; in the terminal it prints after the hand result.

**The send-off.** Leaving the table gets a closing ceremony. Click **Leave**
(离席) in the browser — or `q` in the terminal — and the coach walks you out: a
full-screen 散场陈词 with its closing statement (the night in one line, what
you did well, the habit to fix), over the night's numbers — hands played, net,
follow rate, net listening vs. going your own way, and your leaks by name. One
button sits under it: *Sit back down*. With the API the statement is written
for your actual night; offline it's picked by how the night went (big win,
small win, flat, loss, rough) plus the habit line. A player who leaves without
playing a hand gets told that was possibly the wisest line of the night.

Offline (or the moment the API coughs) the coach is pure arithmetic with canned
lines — the advice never just disappears. Turn it off with `--no-coach` or the
setup checkbox. It needs the equity numbers, so `--no-odds` turns it off too.

### Autopilot — commit before your turn

Decide early and stop waiting on the table:

| | |
|---|---|
| **Fold in advance** (预先弃牌) | you're done with this hand — it checks while checking is free, and folds the moment someone bets |
| **Call everything** (默认全跟) | call whatever comes, all hand |
| **Call this street** (跟当前轮次) | call for the rest of this street only, then the controls come back |
| **Follow the coach** (本轮跟随 AI) | do whatever [the coach](#the-coach) says for the rest of this street — re-read each turn, not fixed at arming time |

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

**They keep a poker face.** Each decision has two channels: a private
`think` — the honest read (hand strength, price, draws, plan) that stays in
the player's head and is never shown to anyone — and an out-loud `say` the
whole table hears. The rules of the prompt forbid speaking the real analysis:
no "it's cheap, I'll take a look", no announcing draws or reads. What they
*do* say out loud is table craft — acting strong when weak, bored when
strong, needling, or just silence — so the words you hear are a read to
decode, not a strategy leak to exploit.

Their talk is still bound to their chips: a player can lie all day about
*what they hold* ("I flopped a set"), but if they announce *what they're
doing* — "I fold", "I'm all in" — the actual move is forced to match. So a
spoken call is a call and a spoken shove is a shove; only the card-strength
story can be a bluff.

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
  ranges.py            Bayesian read of what each opponent holds, and bluff %
  advisor.py           the coach: reads opponents, advises, owns the result
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
- **The ranges.** Strength is asserted to be a real percentile (the average
  holding is 0.5 *by construction*, so a seat that has done nothing reads as
  exactly average). The rest are properties rather than magic numbers: betting
  raises the read, checking lowers it, calling condenses it, a bigger bet
  polarizes it, your own cards are removed from his combos, a folded seat is
  never read, and you can't bluff by calling.
