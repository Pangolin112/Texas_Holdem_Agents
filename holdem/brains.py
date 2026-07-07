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
        # Facing a huge bet, only a genuinely strong hand continues.
        if to_call >= max(player.stack // 2, 4 * bb) and eff < 0.75:
            return Action(FOLD), None
        if eff > pot_odds + 0.28 and can_raise and rng.random() < aggr:
            if strength > 0.92 and rng.random() < aggr * 0.35:
                return Action(ALL_IN), say
            target = int((pot + to_call) * (0.8 + rng.random() * 0.7))
            target = max(min_to, min(target, max_to))
            return Action(RAISE, target), say
        if eff >= pot_odds:
            return Action(CALL), say
        # Loose players peel small bets anyway.
        if to_call <= bb and rng.random() < loose * 0.5:
            return Action(CALL), say
        return Action(FOLD), None

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


# ---------------------------------------------------------------------------
# LLM brain
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATE = """You are {name}, a regular person playing in a friendly No-Limit Texas Hold'em home game with people you know.

Who you are: {style}

Play genuinely good poker in line with who you are: weigh your hand strength, pot odds, position, stack sizes, and how the others have been acting tonight. Bluff when it fits you, and vary your bet sizes so you stay unpredictable.

Discipline matters more than flair: going all-in, or calling one, demands a genuinely strong hand or overwhelming pot odds — folding weak hands to big bets is what winners do. Don't spew chips on hopeless holdings just to look bold.

Respond with ONE JSON object and nothing else:
{{"action": "fold" | "check" | "call" | "raise" | "all_in", "raise_to": <integer, required only for "raise">, "say": "<optional short remark to the table, or empty string>"}}

Hard rules:
- "raise_to" is the TOTAL amount of your bet for this street, not the increment.
- "say" must sound like a normal person at a real card table: plain, casual, reacting to what's actually going on. No catchphrases, no theatrical persona lines, no emoji, nothing scripted-sounding. Most of the time say nothing ("") or keep it to a few words.
- Never state your actual hole cards in "say" (misleading people is fine).
- Don't repeat remarks you've already made tonight.
- Only "check" when there is nothing to call.
- You can talk to anyone at the table in "say" — the human or the other players. Use their name when you mean a specific person, and if someone spoke to you, it's natural to answer them."""


CHAT_SYSTEM_TEMPLATE = """You are {name}, a regular person at a friendly No-Limit Texas Hold'em home game with people you know.

Who you are: {style}

Something just happened at the table — somebody said something, or made a move worth noticing. Respond with ONE short line, the way people actually talk at a card table — plain and casual, max 20 words, no JSON, no quotes around it, no emoji, nothing theatrical or scripted-sounding. Tease, needle, deflect, joke, or answer straight — whatever fits you and the moment. You can talk to whoever it concerns or pull anyone else into it — use a person's name when you mean them specifically. Never reveal your actual hole cards (misleading people is fine). If you have nothing worth saying, reply with exactly: SILENT"""


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


class LLMBrain:
    is_llm = True

    def __init__(self, client, model, personality, rng):
        self.client = client
        self.model = model
        self.p = personality
        self.fallback = HeuristicBrain(personality, rng)
        self._warned = False

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

    def _create(self, messages, json_mode=True):
        kwargs = {"model": self.model, "messages": messages}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.model.startswith(("gpt-5", "o1", "o3", "o4")):
            # Reasoning models: low effort keeps decisions quick at the table.
            kwargs["reasoning_effort"] = "low"
        else:
            kwargs["temperature"] = 1.0
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception:
            # Some models reject response_format / temperature / reasoning
            # settings; retry once with the plain call before giving up.
            resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content or ""

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

    def _parse(self, raw, view):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON in model reply")
        data = json.loads(match.group(0))

        say = str(data.get("say") or "").strip()[:100] or None
        kind = str(data.get("action", "")).strip().lower().replace("-", "_").replace(" ", "_")

        if kind == "bet":
            kind = RAISE
        if kind == FOLD:
            # Folding when checking is free is never right; take the free card.
            return (Action(CHECK) if view["to_call"] == 0 else Action(FOLD)), say
        if kind == CHECK:
            return (Action(CHECK) if view["to_call"] == 0 else Action(CALL)), say
        if kind == CALL:
            return (Action(CHECK) if view["to_call"] == 0 else Action(CALL)), say
        if kind == ALL_IN:
            return Action(ALL_IN), say
        if kind == RAISE:
            if not view["can_raise"]:
                return Action(CALL), say
            try:
                target = int(data.get("raise_to") or 0)
            except (TypeError, ValueError):
                target = view["min_raise_to"]
            target = max(view["min_raise_to"], min(target, view["max_raise_to"]))
            return Action(RAISE, target), say
        raise ValueError("unknown action %r" % kind)
