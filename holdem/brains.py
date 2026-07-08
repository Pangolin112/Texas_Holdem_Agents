"""Decision-making for AI seats.

LLMBrain asks an OpenAI model for a JSON decision built from everything the
agent may legitimately know: its own hole cards, the board, pot, stacks, the
full action history, table talk, and results of previous hands. It never sees
anyone else's hole cards. If the API call fails, HeuristicBrain takes over so
the game keeps moving.
"""

import json
import re

from . import ui
from .cards import Card  # noqa: F401
from . import evaluator
from .players import Action, FOLD, CHECK, CALL, RAISE, ALL_IN


class ModelChain:
    """A preferred model plus fallbacks. If the chosen model isn't available on
    the account, the game steps down to the next one instead of breaking. One
    shared instance is passed to every seat so a downgrade happens only once."""

    def __init__(self, models):
        seen = []
        for m in models:
            if m and m not in seen:
                seen.append(m)
        self.models = seen or ["gpt-5-mini"]
        self.idx = 0

    @property
    def current(self):
        return self.models[self.idx]

    def downgrade(self):
        if self.idx < len(self.models) - 1:
            self.idx += 1
            return True
        return False


def _is_model_error(exc):
    """True if the exception looks like 'this model doesn't exist / no access'
    (as opposed to a transient network or parameter problem)."""
    if "notfound" in type(exc).__name__.lower():
        return True
    msg = str(exc).lower()
    return "model" in msg and any(s in msg for s in (
        "not found", "does not exist", "unknown", "invalid", "no access",
        "not available", "deprecated"))


PERSONALITIES = [
    {
        "name": "Mike",
        "style": ("A retired firefighter in his fifties. Plays too many hands and bets big "
                  "because folding is boring. Loud and friendly — teases people about their "
                  "folds and swears he can read faces."),
        "aggression": 0.85, "looseness": 0.70,
        "taunts": ["Come on, somebody call me for once.", "Folding again? Unbelievable.",
                   "I had you the whole way, you know."],
        "broke_line": "Alright, alright. Put another one on my tab.",
    },
    {
        "name": "Sarah",
        "style": ("An accountant who hates losing money more than she likes winning it. "
                  "Tight and careful, folds without drama. Dry one-liners, notices everything."),
        "aggression": 0.45, "looseness": 0.25,
        "taunts": ["That bet made no sense, just saying.", "I fold. I like my money.",
                   "You always do that on the river."],
        "broke_line": "This is exactly why I don't gamble much. Fine, one more.",
    },
    {
        "name": "Emma",
        "style": ("A med student who hates being pushed out of a hand, so she calls too much. "
                  "Chatty and easily distracted — talks about food, exams and the cards, "
                  "sometimes mid-hand."),
        "aggression": 0.25, "looseness": 0.85,
        "taunts": ["I know I should fold. I'm not going to.", "Why's everyone so serious tonight?",
                   "Okay, one more call and that's it."],
        "broke_line": "Oops. Lend me another buy-in? I'm good for it, promise.",
    },
    {
        "name": "Dave",
        "style": ("A building contractor. Blunt and aggressive — bets big when he smells "
                  "weakness and gets a bit grumpy when it backfires. Trash talk is direct "
                  "but good-natured."),
        "aggression": 0.70, "looseness": 0.60,
        "taunts": ["Let's stop messing around.", "You don't have it. I can tell.",
                   "Fine, take it. Won't happen twice."],
        "broke_line": "Whatever. Stake me again, I'm winning it back.",
    },
    {
        "name": "Linda",
        "style": ("A retired math teacher. Patient, plays few hands but plays them hard, and "
                  "remembers exactly who bluffed whom. Needles people gently, with a smile."),
        "aggression": 0.55, "looseness": 0.40,
        "taunts": ["You did the same thing two hands ago.", "I can wait. I'm very patient.",
                   "That's a lot of chips for a maybe."],
        "broke_line": "Well, that was a lesson. Put it on my account, please.",
    },
    {
        "name": "Frank",
        "style": ("A barber who believes in hot streaks and plays his hunches — almost any "
                  "two cards when he feels 'due'. Easygoing, laughs at his own bad calls."),
        "aggression": 0.50, "looseness": 0.90,
        "taunts": ["I'm due, I can feel it.", "Haven't seen a good card in an hour.",
                   "Can't fold now, I'm on a rush."],
        "broke_line": "Cold deck tonight. One more stack and then I behave.",
    },
    {
        "name": "Ray",
        "style": ("A long-haul truck driver. Quiet — mostly nods and short sentences. Tight "
                  "and aggressive: when he finally puts chips in, he usually has it."),
        "aggression": 0.65, "looseness": 0.30,
        "taunts": ["Yeah, okay.", "Your call.", "Long night."],
        "broke_line": "Hm. Put it on the bill.",
    },
]


# ---------------------------------------------------------------------------
# Heuristic fallback brain (also powers --offline mode)
# ---------------------------------------------------------------------------

class HeuristicBrain:
    is_llm = False

    def __init__(self, personality, rng):
        self.p = personality
        self.rng = rng

    # -- strength estimation ------------------------------------------------

    def _preflop_strength(self, hole):
        a, b = sorted((c.value for c in hole), reverse=True)
        if a == b:
            return 0.50 + (a - 2) / 24.0  # 22 ≈ 0.50 ... AA = 1.0
        s = (a + b) / 27.0 * 0.42
        if hole[0].suit == hole[1].suit:
            s += 0.07
        gap = a - b
        if gap == 1:
            s += 0.06
        elif gap == 2:
            s += 0.03
        if a >= 11 and b >= 11:
            s += 0.12
        elif a == 14:
            s += 0.05
        return min(s, 0.95)

    def _strength(self, hole, board):
        if not board:
            return self._preflop_strength(hole)
        rank, _ = evaluator.best_hand(hole + board)
        base = {0: 0.15, 1: 0.38, 2: 0.55, 3: 0.66, 4: 0.76,
                5: 0.82, 6: 0.91, 7: 0.97, 8: 0.99}[rank[0]]
        # Don't get excited about a made hand that is entirely on the board.
        if len(board) == 5:
            board_rank, _ = evaluator.best_hand(board)
            if board_rank >= rank:
                base = 0.25
        return max(0.05, min(0.99, base + (self.rng.random() - 0.5) * 0.12))

    # -- decision -----------------------------------------------------------

    def decide(self, player, view):
        strength = self._strength(player.hole, view["board"])
        to_call = view["to_call"]
        pot = max(view["pot"], 1)
        aggr = self.p["aggression"]
        loose = self.p["looseness"]
        rng = self.rng
        say = rng.choice(self.p["taunts"]) if rng.random() < 0.18 else None

        min_to = view["min_raise_to"]
        max_to = view["max_raise_to"]
        can_raise = view["can_raise"]
        bb = view["blinds"][1]

        # Short stack: shove or fold, but only with a real hand.
        if player.stack <= 6 * bb and strength > 0.62 - (loose - 0.5) * 0.1:
            return Action(ALL_IN), say

        if to_call == 0:
            urge = strength + (aggr - 0.5) * 0.25
            if can_raise and (urge > 0.62 or rng.random() < aggr * 0.12):
                target = int(pot * (0.5 + rng.random() * 0.7))
                target = max(min_to, min(max(target, bb), max_to))
                if strength > 0.92 and rng.random() < aggr * 0.25:
                    return Action(ALL_IN), say
                return Action(RAISE, target), say
            return Action(CHECK), say

        pot_odds = to_call / float(pot + to_call)
        eff = strength + (loose - 0.5) * 0.22
        # Facing a shove-sized bet, only a genuinely strong hand continues.
        if to_call >= max(player.stack // 2, 5 * bb) and eff < 0.71:
            return Action(FOLD), None
        if eff > pot_odds + 0.28 and can_raise and rng.random() < aggr:
            if strength > 0.92 and rng.random() < aggr * 0.35:
                return Action(ALL_IN), say
            target = int((pot + to_call) * (0.8 + rng.random() * 0.7))
            target = max(min_to, min(target, max_to))
            return Action(RAISE, target), say
        # Don't give up too easily: call a little past strict pot odds, more so
        # for looser players, since folding at the first bet just bleeds chips.
        slack = 0.04 + loose * 0.05
        if eff >= pot_odds - slack:
            return Action(CALL), say
        # Cheap bets get peeled — nobody likes folding for one more small call.
        if to_call <= 2 * bb and rng.random() < 0.25 + loose * 0.35:
            return Action(CALL), say
        return Action(FOLD), None

    def buy_decision(self, player, cap, starting_stack, table=None):
        """Voluntary top-up before the next hand. Returns chips to buy (0 =
        stand pat), never more than `cap`. Only a short stack gets reloaded,
        and looser/bolder players reload sooner and closer to a full stack.
        (`table` is ignored here — the offline brain goes on instinct.)"""
        stack = player.stack
        if stack >= 0.6 * starting_stack:
            return 0  # still deep enough to play — no need to reload
        loose = self.p["looseness"]
        aggr = self.p["aggression"]
        shortness = 1.0 - stack / float(starting_stack)  # ~0 full .. ~1 near broke
        chance = 0.10 + shortness * 0.55 + (loose - 0.5) * 0.30 + (aggr - 0.5) * 0.20
        if self.rng.random() >= chance:
            return 0
        want = starting_stack - stack  # reload back toward a full stack
        return max(0, min(want, cap))

    def chat_reply(self, player, situation, chat, speaker_name, text, addressed=None):
        # Spoken to directly -> almost always answer; general remark -> often;
        # overhearing someone else's exchange -> rarely butt in.
        chance = 0.95 if addressed == "you" else (0.2 if addressed else 0.6)
        if self.rng.random() < chance:
            return self.rng.choice(self.p["taunts"])
        return None

    def react(self, player, situation, chat, event):
        if self.rng.random() < 0.7:
            return self.rng.choice(self.p["taunts"])
        return None

    def explain_move(self, player, situation, chat, questioner, question):
        # No live reasoning model offline, but still give a grounded, coherent
        # answer rather than a throwaway line.
        style = ("aggressive" if self.p["aggression"] > 0.6 else "careful")
        loose = ("I'll gamble with a lot of hands" if self.p["looseness"] > 0.6
                 else "I only get involved with hands I like")
        return (("Fair question, %s. " % questioner)
                + ("I looked at the board and the size of the pot, weighed how strong I "
                   "really was against the price I was being asked to pay, and thought about "
                   "how you'd been betting. ")
                + ("I play %s and %s, so given my position and the stacks it was the line I "
                   "was comfortable with — not a random punt." % (style, loose)))


# ---------------------------------------------------------------------------
# LLM brain
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATE = """You are {name}, a regular person playing in a friendly No-Limit Texas Hold'em home game with people you know.

Who you are: {style}

Everyone here is a regular person like you — friends around a kitchen table, nobody's a computer. Play genuinely good poker in line with who you are: weigh your hand strength, pot odds, position, stack sizes, and how the others have been acting tonight. Bluff when it fits you, and vary your bet sizes so you stay unpredictable.

Don't be a pushover: good players don't fold every time someone bets. Defend your blinds, call with any reasonable hand, pair, or decent draw when the price isn't crazy, and fight back with the occasional float or bluff-raise — folding at the first sign of pressure just bleeds chips and lets people run you over. Save the disciplined lay-downs for when someone commits real money and you genuinely have almost nothing. Only shove all-in with a strong hand or a good read, but between checking, calling, and raising, lean toward staying in the fight rather than giving up.

Respond with ONE JSON object and nothing else:
{{"action": "fold" | "check" | "call" | "raise" | "all_in", "raise_to": <integer, required only for "raise">, "say": "<optional short remark to the table, or empty string>"}}

Hard rules:
- "raise_to" is the TOTAL amount of your bet for this street, not the increment.
- "say" must sound like a normal person at a real card table: plain, casual, reacting to what's actually going on. No catchphrases, no theatrical persona lines, no emoji, nothing scripted-sounding. Most of the time say nothing ("") or keep it to a few words.
- You may bluff and lie freely about WHAT YOU HAVE — your cards, how strong or weak you are. That's the game. But you must NOT misstate WHAT YOU ARE DOING: if your "say" names your move (fold, check, call, raise, all-in), it has to be exactly the move in "action". If you'd rather keep your move to yourself, just don't mention it.
- Don't repeat remarks you've already made tonight.
- Only "check" when there is nothing to call.
- You can talk to anyone at the table in "say". Use their name when you mean a specific person, and if someone spoke to you, it's natural to answer them."""


CHAT_SYSTEM_TEMPLATE = """You are {name}, a regular person at a friendly No-Limit Texas Hold'em home game with people you know.

Who you are: {style}

Something just happened at the table — somebody said something, or made a move worth noticing. Respond with ONE short line, the way people actually talk at a card table — plain and casual, max 20 words, no JSON, no quotes around it, no emoji, nothing theatrical or scripted-sounding. Tease, needle, deflect, joke, or answer straight — whatever fits you and the moment. You can talk to whoever it concerns or pull anyone else into it — use a person's name when you mean them specifically. You can lie about your cards all you want, but don't announce a move (folding, calling, raising, all-in) you aren't actually making. If you have nothing worth saying, reply with exactly: SILENT"""


EXPLAIN_SYSTEM_TEMPLATE = """You are {name}, a sharp, thoughtful poker player at a friendly No-Limit Texas Hold'em home game.

Who you are: {style}

Someone has questioned one of your moves. This is different from ordinary table banter: when asked to justify your play, you give a genuine, well-reasoned explanation — the real poker logic behind your decision, laid out step by step. Reason in terms of your hand strength, the board texture, the pot odds and the exact price you were getting, your position, the stack sizes, your opponents' tendencies this session, and what you were trying to represent. Be specific and reference the actual cards and amounts. Do NOT brush it off with a one-liner or a catchphrase, and never invent nonsense — if you take a line, you can explain why.

Speak in plain, natural language — a few sentences, no JSON, no bullet points, no emoji. One thing you may still guard: if the hand is LIVE and you're still contesting it, you don't have to reveal your exact hole cards and you may even misrepresent them — but the strategic reasoning you give must be real and coherent. Once the hand is over, be fully honest, cards included."""


BUY_SYSTEM_TEMPLATE = """You are {name}, a regular person in a friendly No-Limit Texas Hold'em home game with people you know.

Who you are: {style}

The last hand just finished and the next one is about to start. Before it does, you can top up your chips — buy more from the house so you have a bigger stack in front of you. The chips are added to your stack, but you owe them back: they go on your tab, so it's borrowing to have more ammunition, not free money. Reload if you're short and want to keep playing your game, or if you like having chips to lean on people; keep it small or skip it entirely if you're comfortable, if you're winning, or if you don't like being in the hole. Decide the way {name} really would.

Respond with ONE JSON object and nothing else:
{{"buy": <integer chips to buy, 0 to skip, at most {cap}>}}"""


def format_chat(chat):
    lines = []
    for speaker, to, text in chat[-10:]:
        if to:
            lines.append('%s (to %s): "%s"' % (speaker, to, text))
        else:
            lines.append('%s: "%s"' % (speaker, text))
    return "\n".join(lines) or "(quiet so far)"


def format_history(history):
    lines = []
    current_street = None
    for street, text in history:
        if street != current_street:
            lines.append(street + ":")
            current_street = street
        lines.append("  " + text)
    return "\n".join(lines) if lines else "(no action yet)"


def build_user_prompt(player, view):
    hero = view["hero"]
    board_txt = " ".join(str(c) for c in view["board"]) if view["board"] else "(none yet)"
    hole_txt = " ".join(str(c) for c in hero["hole"])

    seats = []
    for pl in view["players"]:
        tags = []
        if pl["is_button"]:
            tags.append("dealer")
        if pl["is_hero"]:
            tags.append("<-- this is you")
        if pl["folded"]:
            status = "folded"
        elif pl["all_in"]:
            status = "ALL-IN"
        else:
            status = "active, bet %d this street" % pl["bet_street"]
        tag_txt = (" [" + ", ".join(tags) + "]") if tags else ""
        debt_txt = (", debt to the house %d" % pl["debt"]) if pl.get("debt") else ""
        seats.append("- %s%s: stack %d%s — %s" % (pl["name"], tag_txt, pl["stack"], debt_txt, status))

    chat_txt = format_chat(view["chat"])
    memory_txt = "\n".join(view["memory"][-5:]) or "(this is the first hand)"

    made_line = ""
    if view.get("hero_hand_hint"):
        made_line = "\nYour best five-card hand right now: %s." % view["hero_hand_hint"]

    if view["to_call"] == 0:
        call_line = "Nothing to call — you may check."
    else:
        odds = 100.0 * view["to_call"] / (view["pot"] + view["to_call"])
        call_line = ("To call: %d (folding costs nothing, calling costs %d — "
                     "pot odds: you need to win %.0f%% of the time to break even)." % (
                         view["to_call"], min(view["to_call"], hero["stack"]), odds))
    if view["can_raise"]:
        raise_line = ("If you raise: minimum raise_to = %d, maximum raise_to = %d (all-in)."
                      % (view["min_raise_to"], view["max_raise_to"]))
    else:
        raise_line = "You cannot raise — only fold, or call (which puts you all-in)."

    return """HAND #{hand_no} | Street: {street} | Blinds: {sb}/{bb}
Your hole cards: {hole}
Board: {board}{made_line}
Pot: {pot}
Your stack: {stack} (you've bet {bet_street} this street, {committed} total this hand)
{call_line}
{raise_line}

Players in seat order:
{seats}

Action so far this hand:
{history}

Recent table talk:
{chat}

Earlier hands this session:
{memory}

What do you do? Respond with the JSON object only.""".format(
        hand_no=view["hand_no"], street=view["street"],
        sb=view["blinds"][0], bb=view["blinds"][1],
        hole=hole_txt, board=board_txt, made_line=made_line, pot=view["pot"],
        stack=hero["stack"], bet_street=hero["bet_street"], committed=hero["committed"],
        call_line=call_line, raise_line=raise_line,
        seats="\n".join(seats), history=format_history(view["history"]),
        chat=chat_txt, memory=memory_txt)


# ---------------------------------------------------------------------------
# Keeping words honest: a player may lie about their CARDS, but if their spoken
# line names the move they're making, the actual move must match it.
# ---------------------------------------------------------------------------

_NEG_RE = re.compile(r"\b(?:not|never|no|n't|won'?t|don'?t|wouldn'?t|can'?t|"
                     r"maybe|might|if|unless|almost|nearly)\b")

# First-person declarations. Each entry: (action, regex). Anchored to "I" so a
# comment about someone else ("you fold too much", "nice call") never matches.
_SELF_DECL = [
    (FOLD,  re.compile(r"\bi(?:'?m| am| will|'?ll)?\s+(?:fold|folding|out|done|"
                       r"giv\w* up|muck\w*|gone)\b")),
    (RAISE, re.compile(r"\bi(?:'?m| am| will|'?ll)?\s+(?:raise|raising|re-?raise|"
                       r"bump\w*)\b")),
    (CALL,  re.compile(r"\bi(?:'?m| am| will|'?ll)?\s+call(?:ing)?\b")),
    (CHECK, re.compile(r"\bi(?:'?m| am| will|'?ll)?\s+check(?:ing)?\b")),
]
# All-in: either an "I ..." lead-in or a bare shove phrase in the speaker's own
# line. Guarded below against second-person and questions ("you all in?").
_ALLIN_SELF = re.compile(r"\bi(?:'?m| am| will|'?ll)?\s+(?:[a-z']+\s+){0,3}?"
                         r"(?:all[\s-]?in|shov\w*|jam\w*|shipp?ing? it)\b")
_ALLIN_BARE = re.compile(r"\b(?:all[\s-]?in|shov(?:e|ing)|jam(?:ming)?|"
                         r"shipp?ing? it)\b")


def _blocked(low, m):
    """A declaration is void if a negation/hedge sits just before it or inside
    the matched span ('I'm not going all in', 'maybe I fold')."""
    before = low[max(0, m.start() - 12):m.start()]
    return bool(_NEG_RE.search(before) or _NEG_RE.search(m.group(0)))


def spoken_action(say):
    """If `say` clearly declares the speaker's own move, return that action
    kind; otherwise None. Conservative: ambiguous or conflicting talk -> None,
    so the mechanical action is left untouched."""
    if not say:
        return None
    low = " " + say.lower() + " "
    found = set()

    for kind, rx in _SELF_DECL:
        m = rx.search(low)
        if m and not _blocked(low, m):
            found.add(kind)

    m = _ALLIN_SELF.search(low)
    allin = m is not None and not _blocked(low, m)
    if not allin:
        m = _ALLIN_BARE.search(low)
        # A bare shove counts only in the speaker's own statement: no "you",
        # not a question ("you going all in?", "are you all in?").
        if m and not _blocked(low, m) and "you" not in low and "?" not in low:
            allin = True
    if allin:
        found.add(ALL_IN)

    return found.pop() if len(found) == 1 else None


def reconcile_action(action, say, view, raise_to=None):
    """Make the move honor the spoken word. Returns (action, say). If the word
    can't be honored legally, drop the misleading say instead of lying."""
    decl = spoken_action(say)
    if decl is None:
        return action, say
    to_call = view["to_call"]

    if decl == FOLD:
        want = CHECK if to_call == 0 else FOLD
    elif decl == CALL:
        want = CHECK if to_call == 0 else CALL
    elif decl == CHECK:
        if to_call != 0:            # can't legally check facing a bet
            return action, say
        want = CHECK
    elif decl == RAISE:
        if not view["can_raise"]:   # can't raise here — don't lie about it
            return action, None
        want = RAISE
    else:  # ALL_IN
        want = ALL_IN

    if want == action.kind:
        return action, say          # already consistent, the common case

    if want == RAISE:
        amount = action.amount if action.kind == RAISE else 0
        if not amount:
            try:
                amount = int(raise_to or 0)
            except (TypeError, ValueError):
                amount = 0
        amount = max(view["min_raise_to"], min(amount or view["min_raise_to"],
                                               view["max_raise_to"]))
        return Action(RAISE, amount), say
    return Action(want), say


class LLMBrain:
    is_llm = True

    def __init__(self, client, model, personality, rng):
        self.client = client
        # `model` may be a plain id (tests, simple calls) or a shared ModelChain.
        self.chain = model if isinstance(model, ModelChain) else ModelChain([model])
        self.p = personality
        self.fallback = HeuristicBrain(personality, rng)
        self._warned = False

    @property
    def model(self):
        return self.chain.current

    def decide(self, player, view):
        ui.thinking(player.name)
        try:
            raw = self._ask(player, view)
            return self._parse(raw, view)
        except Exception as exc:  # any API/parse failure -> heuristic keeps game alive
            if not self._warned:
                ui.warn("%s's uplink glitched (%s: %s) — playing on instinct."
                        % (player.name, type(exc).__name__, str(exc)[:120]))
                self._warned = True
            return self.fallback.decide(player, view)

    def buy_decision(self, player, cap, starting_stack, table=None):
        """Let the agent genuinely decide, via the model, how many chips to buy
        before the next hand (0 to skip, at most `cap`). Only a seat below a
        full buy-in bothers to weigh it — a comfortably stacked one stands pat
        without spending a call. Any API/parse failure falls back to instinct."""
        if player.stack >= starting_stack:
            return 0
        try:
            return self._ask_buy(player, cap, starting_stack, table or {})
        except Exception:
            return self.fallback.buy_decision(player, cap, starting_stack, table)

    def _ask_buy(self, player, cap, starting_stack, table):
        sb, bb = table.get("blinds", (0, 0))
        standings = table.get("standings") or []
        stand_txt = "\n".join(
            "- %s: stack %d%s" % (n, s, (", owes the house %d" % d) if d else "")
            for n, s, d in standings) or "(just you at the table)"
        memory = table.get("memory") or []
        mem_txt = "\n".join(memory[-5:]) or "(this is the first hand)"
        messages = [
            {"role": "system", "content": BUY_SYSTEM_TEMPLATE.format(
                name=player.name, style=self.p["style"], cap=cap)},
            {"role": "user", "content":
                ("Your stack: %d. Your tab so far: %d. A full buy-in is %d. Blinds %d/%d.\n\n"
                 "How everyone stands right now (by net worth):\n%s\n\n"
                 "Recent hands this session:\n%s\n\n"
                 "How many chips do you buy before the next hand? 0 to skip, at most %d. "
                 "Respond with the JSON object only."
                 % (player.stack, player.debt, starting_stack, sb, bb,
                    stand_txt, mem_txt, cap))},
        ]
        raw = self._create(messages)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON in buy reply")
        amount = int(json.loads(match.group(0)).get("buy") or 0)
        return max(0, min(amount, cap))

    def _one_call(self, model, messages, json_mode, effort, plain=False):
        kwargs = {"model": model, "messages": messages}
        if not plain:
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if model.startswith(("gpt-5", "o1", "o3", "o4")):
                kwargs["reasoning_effort"] = effort
            else:
                kwargs["temperature"] = 1.0
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def _create(self, messages, json_mode=True, effort="low"):
        # `effort` trades speed for depth: "low" for quick decisions and banter,
        # higher when the player asks a seat to justify its reasoning.
        last = None
        for _ in range(len(self.chain.models) + 1):
            model = self.chain.current
            try:
                return self._one_call(model, messages, json_mode, effort)
            except Exception as exc:
                last = exc
                if _is_model_error(exc):
                    if self.chain.downgrade():
                        ui.warn("model '%s' unavailable — switching to '%s'."
                                % (model, self.chain.current))
                        continue
                    raise
                # A response_format / temperature / reasoning quirk: retry once
                # as a plain call before giving up on this model.
                try:
                    return self._one_call(model, messages, json_mode, effort, plain=True)
                except Exception as exc2:
                    last = exc2
                    if _is_model_error(exc2) and self.chain.downgrade():
                        continue
                    raise
        raise last

    def _ask(self, player, view):
        messages = [
            {"role": "system",
             "content": SYSTEM_TEMPLATE.format(name=player.name, style=self.p["style"])},
            {"role": "user", "content": build_user_prompt(player, view)},
        ]
        return self._create(messages)

    def _one_liner(self, player, body):
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_TEMPLATE.format(
                name=player.name, style=self.p["style"])},
            {"role": "user", "content": body},
        ]
        raw = self._create(messages, json_mode=False).strip()
        line = raw.splitlines()[0].strip().strip('"').strip() if raw else ""
        if not line or line.upper() == "SILENT":
            return None
        return line[:140]

    def chat_reply(self, player, situation, chat, speaker_name, text, addressed=None):
        try:
            if addressed == "you":
                said = ('%s just spoke to YOU: "%s" — answer them.'
                        % (speaker_name, text))
            elif addressed:
                said = ('%s just said to %s: "%s" — you\'re only overhearing this; '
                        'chime in only if you have something worth adding.'
                        % (speaker_name, addressed, text))
            else:
                said = '%s just said to the table: "%s"' % (speaker_name, text)
            return self._one_liner(player,
                                   "%s\n\nRecent table talk:\n%s\n\n%s\n"
                                   "Your reply (one short line, or SILENT):"
                                   % (situation, format_chat(chat), said))
        except Exception:
            return self.fallback.chat_reply(player, situation, chat,
                                            speaker_name, text, addressed)

    def react(self, player, situation, chat, event):
        try:
            return self._one_liner(player,
                                   "%s\n\nRecent table talk:\n%s\n\nWhat just happened: %s\n"
                                   "If that's worth a remark, say one short line (name whoever "
                                   "it concerns if natural); otherwise reply exactly SILENT:"
                                   % (situation, format_chat(chat), event))
        except Exception:
            return self.fallback.react(player, situation, chat, event)

    def explain_move(self, player, situation, chat, questioner, question):
        """The player questioned this seat's play — give the real reasoning,
        step by step, not a one-liner. Kept at "low" reasoning effort: the
        prompt already asks for the genuine step-by-step logic, and low effort
        answers fast enough that the human isn't left waiting — a laggy reply
        kills the back-and-forth even when the content is good."""
        ui.thinking(player.name)  # show feedback while the model composes
        try:
            body = ("%s is questioning your play: \"%s\"\n\n"
                    "The situation and the action this hand:\n%s\n\n"
                    "Recent table talk:\n%s\n\n"
                    "Answer %s directly and walk them through your ACTUAL thinking on that "
                    "decision, step by step: your read on the board, how strong you were, the "
                    "pot odds and the price you were getting, your position, the stack sizes, "
                    "what you were trying to represent, and what you expected them to do. "
                    "Reference the real cards and amounts. Be concrete and logical — a few "
                    "plain sentences, no catchphrases, no dodging."
                    % (questioner, question, situation, format_chat(chat), questioner))
            messages = [
                {"role": "system", "content": EXPLAIN_SYSTEM_TEMPLATE.format(
                    name=player.name, style=self.p["style"])},
                {"role": "user", "content": body},
            ]
            raw = self._create(messages, json_mode=False, effort="low").strip()
            text = " ".join(raw.split())  # fold any line breaks into one spoken turn
            if not text or text.upper() == "SILENT":
                return None
            return text[:500]
        except Exception:
            return self.fallback.explain_move(player, situation, chat, questioner, question)

    def _parse(self, raw, view):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON in model reply")
        data = json.loads(match.group(0))

        say = str(data.get("say") or "").strip()[:100] or None
        action = self._mechanical_action(data, view)
        # A player may bluff about their cards, but their spoken move must match
        # what they actually do — reconcile any mismatch in favor of the words.
        return reconcile_action(action, say, view, data.get("raise_to"))

    @staticmethod
    def _mechanical_action(data, view):
        kind = str(data.get("action", "")).strip().lower().replace("-", "_").replace(" ", "_")
        if kind == "bet":
            kind = RAISE
        if kind == FOLD:
            # Folding when checking is free is never right; take the free card.
            return Action(CHECK) if view["to_call"] == 0 else Action(FOLD)
        if kind in (CHECK, CALL):
            return Action(CHECK) if view["to_call"] == 0 else Action(CALL)
        if kind == ALL_IN:
            return Action(ALL_IN)
        if kind == RAISE:
            if not view["can_raise"]:
                return Action(CALL)
            try:
                target = int(data.get("raise_to") or 0)
            except (TypeError, ValueError):
                target = view["min_raise_to"]
            target = max(view["min_raise_to"], min(target, view["max_raise_to"]))
            return Action(RAISE, target)
        raise ValueError("unknown action %r" % kind)
