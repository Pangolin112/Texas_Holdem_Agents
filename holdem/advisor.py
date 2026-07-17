"""The coach standing behind your chair.

Three jobs, in order of how much they matter:

1. **Read the table.** Every opponent's betting *this hand* is evidence about
   what they hold. A seat that raised twice is representing a narrow, strong
   range; one that has called along all night is wide and weak. That read is
   built from the structured action log — never from anyone's hole cards, which
   the advisor is not allowed to see. It only knows what you know.

2. **Tell you what to do.** `odds.hand_odds` says how often you win against
   *random* hands. But nobody plays random hands, and a table that's screaming
   at you is not random — so the read discounts your raw equity, and the
   discounted number is what gets compared to the price you're being offered.
   That comparison is the whole recommendation: call when equity beats pot odds,
   fold when it doesn't, raise when you're far enough ahead to get paid.

3. **Own the result.** A coach who is never wrong out loud is worthless. When
   the hand ends the advisor is told what actually happened, whether you
   listened, and (from what the table showed) whether it was right — and has to
   say so: smug when it called it, self-deprecating when it blew it.

There are two of them. `LLMAdvisor` thinks in the model and talks like a person.
`HeuristicAdvisor` is pure arithmetic with canned lines, runs offline, and is
also what the LLM one falls back to the moment the API coughs — so advice never
just disappears mid-hand.
"""

from __future__ import annotations

import json
import random
import re
from typing import Any, Optional

from . import odds, ranges, ui
from .brains import ModelCaller, _lang_note
from .players import ALL_IN, CALL, CHECK, FOLD, RAISE, advice_action  # noqa: F401

# Re-simulating against their ranges is a second pass over the same maths, so
# it gets a shorter clock than the headline number.
RANGE_EQUITY_BUDGET = 0.18

# The coach's identity: a name for the voice/TTS lookup, and a style the model
# is asked to write in. Front-ends title the panel themselves (localized), so
# the name is only ever used for attribution and the spoken voice.
ADVISOR = {
    "name": "Coach",
    "style": ("a blunt, dry poker coach who has watched this game for thirty "
              "years, likes the player but has no patience for wishful "
              "thinking, and would rather be useful than polite"),
    "voice": "sage",
    "tts_style": "dry, unhurried, faintly amused; a coach who has seen this exact spot a thousand times",
}

# How a seat's betting reads. Front-ends turn these keys into text (and into
# Chinese), so the vocabulary is fixed and small on purpose.
READ_SHOVED = "shoved"          # all-in: the nuts or nothing
READ_POLARIZED = "polarized"    # huge late bet: same, but you still have a fold
READ_STRONG = "strong"          # repeated aggression: narrow, strong range
READ_AGGRESSIVE = "aggressive"  # one raise: better than average
READ_CALLING = "calling"        # along for the ride: draws, medium pairs
READ_PASSIVE = "passive"        # checking it down: little to nothing
READ_QUIET = "quiet"            # hasn't done anything worth reading

# Rough hand-strength each read implies, on the same 0-1 scale as equity.
# BASELINE is what a random unknown hand is worth — reads below it mean the
# seat looks *weaker* than a stranger, which is a reason to bet, not to fold.
BASELINE = 0.35
READ_STRENGTH = {
    READ_SHOVED: 0.80,
    READ_POLARIZED: 0.75,
    READ_STRONG: 0.72,
    READ_AGGRESSIVE: 0.55,
    READ_CALLING: 0.40,
    READ_PASSIVE: 0.28,
    READ_QUIET: BASELINE,
}

# Tone of the post-hand word. The front-end styles by these.
TONE_TOLD_YOU = "told_you"      # you listened, it worked: "what did I say"
TONE_VINDICATED = "vindicated"  # you didn't listen, it cost you: "果然如此"
TONE_HUMBLED = "humbled"        # it was wrong, and has to wear it
TONE_SHRUG = "shrug"            # nothing to crow about either way


def read_opponents(players, actions, street, estimates=None):
    """What each live opponent's betting says about their hand.

    The label ("he's raised twice") is a caption; the numbers underneath come
    from holdem/ranges.py, which works out an actual posterior over every hand
    he can hold — including how much of it is air, which is the bluff number.
    Reads only the action log and the board. Never a hole card.
    """
    estimates = estimates or {}
    reads = []
    for info in players:
        if info["is_hero"] or info["folded"]:
            continue
        mine = [a for a in actions if a["name"] == info["name"]]
        raises = [a for a in mine if a["kind"] in ("bet", "raise", "all_in")]
        calls = [a for a in mine if a["kind"] == "call"]
        checks = [a for a in mine if a["kind"] == "check"]
        # Biggest bet this hand as a fraction of the pot it went into: the
        # single most informative number about a bet, and the one players
        # forget to look at.
        heat = 0.0
        for a in raises:
            pot = max(1, a["pot"])
            heat = max(heat, a["amount"] / float(pot))

        if info["all_in"]:
            key = READ_SHOVED
        elif heat >= 1.0 and street in ("TURN", "RIVER"):
            key = READ_POLARIZED
        elif len(raises) >= 2:
            key = READ_STRONG
        elif len(raises) == 1:
            key = READ_AGGRESSIVE
        elif calls:
            key = READ_CALLING
        elif checks:
            key = READ_PASSIVE
        else:
            key = READ_QUIET

        est = estimates.get(info["name"])
        if est is not None:
            strength = est["mean_strength"]
        else:
            # No posterior (no board to rank against, say) — fall back to what
            # the label alone implies.
            strength = min(0.92, READ_STRENGTH[key] + 0.06 * min(2.0, heat))
        reads.append({
            "name": info["name"],
            "key": key,
            "strength": round(strength, 3),
            "raises": len(raises),
            "calls": len(calls),
            "heat": round(heat, 2),
            "bluff": None if est is None else _round(est["bluff"]),
            "semi_bluff": None if est is None else _round(est["semi_bluff"]),
            "buckets": [] if est is None else [
                {"key": b["key"], "p": round(b["p"], 3)}
                for b in est["buckets"] if b["p"] >= 0.005],
            "combos": None if est is None else len(est["combos"]),
            "note": None,   # the LLM advisor fills this in, in the table language
        })
    reads.sort(key=lambda r: -r["strength"])
    return reads


def _round(x):
    return None if x is None else round(x, 3)


def threat_level(reads):
    """How dangerous the table looks, 0-1, from the scariest live opponent."""
    if not reads:
        return BASELINE
    return max(r["strength"] for r in reads)


def discount_equity(equity, reads):
    """Equity is measured against *random* hands. Real opponents who are
    betting at you do not hold random hands, so shade it toward reality.

    Capped at a third: this is a correction, not a second opinion, and a read
    is never certain enough to overrule the maths outright.
    """
    threat = threat_level(reads)
    if threat <= BASELINE:
        return equity
    excess = (threat - BASELINE) / (1.0 - BASELINE)   # 0 at baseline, 1 at terror
    return equity * (1.0 - 0.33 * excess)


def pot_odds(to_call, pot):
    """The price you're being offered: the share of the final pot you'd be
    buying. Break even by winning exactly this often."""
    if to_call <= 0:
        return 0.0
    return to_call / float(pot + to_call)


def advice_command(advice):
    """The terminal command that carries out `advice` — the one place that
    mapping lives, so the web button, the autopilot and the terminal all follow
    the same advice the same way."""
    if not advice:
        return None
    kind = advice.get("action")
    if kind == FOLD:
        return "f"
    if kind == ALL_IN:
        return "a"
    if kind == RAISE and advice.get("amount"):
        return "r %d" % int(advice["amount"])
    return "c"   # check and call are the same key


def followed_advice(advice, action):
    """Did the player do what they were told? Sizing is judged loosely — a raise
    to 180 instead of 200 is taking the advice, not defying it."""
    if not advice or action is None:
        return True
    want, got = advice.get("action"), action.kind
    if want == got:
        if want != RAISE:
            return True
        target = float(advice.get("amount") or 0)
        if target <= 0:
            return True
        return abs((action.amount or 0) - target) <= max(1.0, target * 0.34)
    # Shoving when told to raise (or raising when told to shove) is still
    # aggression — the coach asked for a bet and got one.
    return {want, got} == {RAISE, ALL_IN}


class HeuristicAdvisor:
    """Your equity against their range, against the price. No API, no waiting."""

    is_llm = False

    def __init__(self, rng, lang="en", range_budget=RANGE_EQUITY_BUDGET):
        self.rng = rng
        self.lang = lang
        self.range_budget = range_budget

    # -- the recommendation ------------------------------------------------

    def advise(self, view, odds_payload):
        equity = float(odds_payload["equity"])
        estimates = ranges.estimate(view)
        reads = read_opponents(view["players"], view["actions"], view["street"],
                               estimates)
        adjusted, exact = self._against_their_range(view, equity, estimates)
        to_call = view["to_call"]
        pot = view["pot"]
        price = pot_odds(to_call, pot)
        stack = view["hero"]["stack"]

        action, amount, key = self._choose(view, adjusted, price, to_call, pot, stack)
        # Confidence is how far from the fence the call is — a spot where equity
        # and price are neck and neck is a coin flip and should say so.
        edge = abs(adjusted - price) if to_call > 0 else abs(adjusted - 0.5)
        confidence = max(0.15, min(0.95, 0.35 + 1.6 * edge))
        return {
            "action": action,
            "amount": amount,
            "key": key,
            "confidence": round(confidence, 2),
            "equity": round(equity, 4),
            "adjusted": round(adjusted, 4),
            "pot_odds": round(price, 4),
            "threat": round(threat_level(reads), 3),
            "vs_range": exact,
            "to_call": to_call,
            "pot": pot,
            "reads": reads,
            "line": self._line(key, view, adjusted, price),
            "reasoning": None,
            "source": "instinct",
        }

    def _against_their_range(self, view, equity, estimates):
        """Your equity against what they're actually representing.

        `equity` is measured against random hands, which is the right baseline
        and the wrong opponent. Given a posterior for each live seat we can just
        re-run the same simulation dealing them hands from their ranges — a real
        number rather than a fudge factor. Returns (equity, was_it_simulated);
        with no posterior to work from it falls back to shading the raw number.
        """
        live = [p["name"] for p in view["players"]
                if not p["is_hero"] and not p["folded"]]
        mine = [estimates.get(n) for n in live]
        if not live or not all(mine):
            return discount_equity(equity, read_opponents(
                view["players"], view["actions"], view["street"], estimates)), False
        out = odds.hand_odds(view["hero"]["hole"], view["board"], len(live),
                             self.rng, ranges=mine,
                             time_budget=self.range_budget)
        if out is None:
            return equity, False
        return out["equity"], True

    def _choose(self, view, adjusted, price, to_call, pot, stack):
        can_raise = view["can_raise"]
        min_to, max_to = view["min_raise_to"], view["max_raise_to"]

        if to_call <= 0:
            # Nothing to pay. Betting is only worth it with something to bet.
            if adjusted >= 0.62 and can_raise:
                return RAISE, self._size(view, adjusted, pot), "value_bet"
            if adjusted >= 0.45 and can_raise and self.rng.random() < 0.25:
                return RAISE, self._size(view, 0.5, pot), "probe"
            return CHECK, 0, "free_card"

        if adjusted < price - 0.02:
            return FOLD, 0, "priced_out"
        if adjusted >= 0.78 and can_raise and max_to >= min_to:
            if to_call >= stack * 0.6:
                return ALL_IN, 0, "jam"
            return RAISE, self._size(view, adjusted, pot), "raise_value"
        if adjusted >= 0.60 and can_raise and adjusted > price + 0.18:
            return RAISE, self._size(view, adjusted, pot), "raise_value"
        if adjusted < price + 0.04:
            return CALL, 0, "thin_call"
        return CALL, 0, "call_price"

    def _size(self, view, strength, pot):
        """Bet a fraction of the pot that grows with how far ahead you are —
        the standard value ladder, clamped to what's legal here."""
        to_call = view["to_call"]
        frac = 0.5 if strength < 0.7 else (0.75 if strength < 0.85 else 1.0)
        target = view["hero"]["bet_street"] + to_call + frac * (pot + to_call)
        return int(max(view["min_raise_to"], min(view["max_raise_to"], round(target))))

    # -- the talking -------------------------------------------------------

    LINES = {
        "priced_out": [
            ("You're not getting the right price. Let it go.", "价格不对，别跟了，弃牌。"),
            ("The maths says no. Fold and keep the chips.", "算下来不划算，弃了吧，筹码留着。"),
        ],
        "thin_call": [
            ("It's close enough to call, but don't fall in love.", "勉强够本，可以跟，但别太上头。"),
            ("Marginal. Call, and be ready to give up.", "很边缘。跟一个，但随时准备放弃。"),
        ],
        "call_price": [
            ("You're getting a fair price. Call.", "这个价格合适，跟。"),
            ("Worth the call at this price.", "这价钱值得跟。"),
        ],
        "raise_value": [
            ("You're ahead. Bet it — make them pay.", "你领先，加注，让他们出钱。"),
            ("This is a raise. Don't just call with the best hand.", "该加注了。拿着最好的牌别只会跟。"),
        ],
        "jam": [
            ("Get it all in. You're not folding this.", "全下吧，这牌你不可能弃。"),
            ("Shove. There's nothing to think about here.", "推了，没什么好想的。"),
        ],
        "value_bet": [
            ("Nobody's betting for you. Bet it yourself.", "没人替你下注，自己下。"),
            ("Free money on the table — bet.", "白送的钱，下注。"),
        ],
        "probe": [
            ("Nobody wants this pot. Take a stab at it.", "这池子没人要，试着偷一下。"),
            ("Try a small one — they'll fold more than they should.", "小下一个试试，他们弃得比应该的多。"),
        ],
        "free_card": [
            ("Check. Take the free card.", "过牌，白看一张。"),
            ("Nothing to pay, nothing to prove. Check.", "不用花钱也没什么好秀的，过。"),
        ],
    }

    def _line(self, key, view, adjusted, price):
        options = self.LINES.get(key) or self.LINES["free_card"]
        en, zh = self.rng.choice(options)
        return zh if self.lang == "zh" else en

    # -- owning the result -------------------------------------------------

    VERDICTS = {
        TONE_TOLD_YOU: [
            ("What did I say.", "我说什么来着。"),
            ("Textbook. Do that again.", "教科书。下次还这么打。"),
        ],
        TONE_VINDICATED: [
            ("I did tell you.", "我提醒过你了。"),
            ("Yeah. That's exactly what I said would happen.", "果然如此，我早说了。"),
        ],
        TONE_HUMBLED: [
            ("...Right. Forget I said anything.", "……行吧，当我没说。"),
            ("Well. I'll be charging you less for that one.", "好吧，这条建议给你打个折。"),
            ("That one's on me. Nice hand.", "这条算我的锅。打得好。"),
        ],
        TONE_SHRUG: [
            ("Fine. On to the next one.", "行吧，下一手。"),
            ("Nothing to learn from that one.", "这手没什么好学的。"),
        ],
    }

    def verdict(self, context):
        tone = verdict_tone(context)
        en, zh = self.rng.choice(self.VERDICTS[tone])
        return tone, (zh if self.lang == "zh" else en)

    DEFIANCE = {
        FOLD: [("Folding there. Bold.", "这就弃了。有种。")],
        CHECK: [("Checking it is, then.", "那就过牌吧。")],
        CALL: [("Calling anyway. Noted.", "还是跟了。记下了。")],
        RAISE: [("Raising. That's not what I said, but alright.", "加注。我可没这么说，但行吧。")],
        ALL_IN: [("All-in. Well. Good luck.", "全下。行……那祝你好运。")],
    }

    def on_defiance(self, advice, action, view):
        options = self.DEFIANCE.get(action.kind) or self.DEFIANCE[CALL]
        en, zh = self.rng.choice(options)
        return zh if self.lang == "zh" else en


def verdict_tone(context):
    """Which way the coach gets to talk, given what actually happened.

    `context["right"]` is None when the table never showed enough to judge —
    then there's nothing to crow about and it says so.
    """
    followed = context["followed"]
    right = context.get("right")
    if right is None:
        return TONE_SHRUG
    if followed and right:
        return TONE_TOLD_YOU
    if followed and not right:
        return TONE_HUMBLED       # you did as told and it cost you: own it
    if not followed and right:
        return TONE_VINDICATED    # you ignored it and it cost you
    return TONE_HUMBLED           # you ignored it and it worked: eat it


ADVISE_SYSTEM = """You are {name}, {style}. You are NOT playing — you stand behind one player and tell them what to do.

You get: their cards, the board, the price they're facing, a Monte-Carlo estimate of how often they win against random hands, and what every opponent has actually DONE this hand. You do NOT get to see anyone's hole cards, and you must never pretend to. Your reads come from betting patterns only.

Respond with JSON only:
{{"action": "fold" | "check" | "call" | "raise" | "all_in",
  "raise_to": <total chips for this street, only when action is "raise">,
  "confidence": <0.0-1.0>,
  "line": "<one short sentence, said out loud to the player>",
  "reasoning": "<2-3 sentences: the price, the read, the decision>",
  "reads": [{{"name": "<opponent>", "note": "<short read on their likely range>"}}]}}

Be concrete about the money. The maths matters more than your gut, but a table that is screaming at you is real information the maths does not have — say when you're overriding the number and why. Never hedge into uselessness: pick one action."""

VERDICT_SYSTEM = """You are {name}, {style}. The hand just ended. You told the player what to do; now you find out whether you were right.

Say ONE short sentence to them, out loud. Match the tone you're given:
- told_you: they listened and it worked. Be smug about it, briefly.
- vindicated: they ignored you and it cost them. "I did say."
- humbled: you were WRONG. Own it — self-deprecating, no excuses, no lecturing.
- shrug: nothing conclusive. Don't manufacture drama.

Never explain at length, never moralize, never repeat the numbers back. One sentence. No JSON, no quotes around it."""

DEFIANCE_SYSTEM = """You are {name}, {style}. You just told the player what to do and they did something else, right in front of you.

Say ONE short sentence reacting to what they actually did. Dry, not preachy — you'll find out soon enough who was right. No JSON, no quotes."""


class LLMAdvisor(ModelCaller):
    """The coach with a model behind it. Falls straight back to arithmetic on
    any API or parse failure, so the panel never goes blank mid-hand."""

    is_llm = True

    def __init__(self, client, model, rng, lang="en",
                 range_budget=RANGE_EQUITY_BUDGET):
        super().__init__(client, model)
        self.rng = rng
        self.lang = lang
        self.fallback = HeuristicAdvisor(rng, lang, range_budget)
        self._warned = False

    def advise(self, view, odds_payload):
        base = self.fallback.advise(view, odds_payload)
        if self.client is None:
            return base
        ui.thinking(ADVISOR["name"])
        try:
            data = self._ask_advice(view, odds_payload, base)
        except Exception as exc:
            if not self._warned:
                ui.warn("the coach's uplink glitched (%s: %s) — advising on instinct."
                        % (type(exc).__name__, str(exc)[:100]))
                self._warned = True
            return base
        return self._merge(base, data, view)

    def _merge(self, base, data, view):
        """Take the model's call, but keep it legal and keep the arithmetic —
        the numbers are ours, only the judgement and the words are the model's."""
        kind = str(data.get("action", "")).strip().lower()
        if kind not in (FOLD, CHECK, CALL, RAISE, ALL_IN):
            return base
        if kind == FOLD and view["to_call"] <= 0:
            kind = CHECK       # never fold for free, whatever it says
        if kind == RAISE and not view["can_raise"]:
            kind = CALL if view["to_call"] > 0 else CHECK
        amount = 0
        if kind == RAISE:
            amount = int(data.get("raise_to") or 0)
            amount = max(view["min_raise_to"], min(view["max_raise_to"], amount))
            if amount >= view["max_raise_to"]:
                kind, amount = ALL_IN, 0
        out = dict(base, action=kind, amount=amount, source="llm")
        line = _one_sentence(data.get("line"))
        if line:
            out["line"] = line
        reasoning = str(data.get("reasoning") or "").strip()
        if reasoning:
            out["reasoning"] = reasoning[:400]
        try:
            confidence = float(data.get("confidence"))
            out["confidence"] = round(max(0.05, min(0.99, confidence)), 2)
        except (TypeError, ValueError):
            pass
        # Graft the model's per-opponent reads onto our structured rows, so the
        # bars stay honest arithmetic and the words come from the coach.
        notes = {}
        for row in data.get("reads") or []:
            if isinstance(row, dict) and row.get("name"):
                notes[str(row["name"])] = str(row.get("note") or "")[:120]
        for read in out["reads"]:
            if notes.get(read["name"]):
                read["note"] = notes[read["name"]]
        return out

    def _ask_advice(self, view, odds_payload, base):
        messages = [
            {"role": "system", "content": ADVISE_SYSTEM.format(
                name=ADVISOR["name"], style=ADVISOR["style"]) + _lang_note(self.lang)},
            {"role": "user", "content": build_advice_prompt(view, odds_payload, base)},
        ]
        raw = self._create(messages, json_mode=True, effort="low")
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON in advice reply")
        return json.loads(match.group(0))

    def verdict(self, context):
        tone = verdict_tone(context)
        if self.client is None:
            return self.fallback.verdict(context)
        try:
            messages = [
                {"role": "system", "content": VERDICT_SYSTEM.format(
                    name=ADVISOR["name"], style=ADVISOR["style"]) + _lang_note(self.lang)},
                {"role": "user", "content": build_verdict_prompt(context, tone)},
            ]
            line = _one_sentence(self._create(messages, json_mode=False, effort="low"))
        except Exception:
            return self.fallback.verdict(context)
        if not line:
            return self.fallback.verdict(context)
        return tone, line

    def on_defiance(self, advice, action, view):
        if self.client is None:
            return self.fallback.on_defiance(advice, action, view)
        try:
            told = advice.get("action")
            if advice.get("action") == RAISE and advice.get("amount"):
                told = "raise to %d" % advice["amount"]
            did = action.kind
            if action.kind == RAISE and action.amount:
                did = "raise to %d" % action.amount
            messages = [
                {"role": "system", "content": DEFIANCE_SYSTEM.format(
                    name=ADVISOR["name"], style=ADVISOR["style"]) + _lang_note(self.lang)},
                {"role": "user", "content":
                    ("You said: %s. They did: %s.\nBoard: %s. Pot: %d.\nYour line was: \"%s\"\n\n"
                     "React in one sentence."
                     % (told, did, _board_text(view["board"]), view["pot"],
                        advice.get("line") or ""))},
            ]
            line = _one_sentence(self._create(messages, json_mode=False, effort="low"))
        except Exception:
            return self.fallback.on_defiance(advice, action, view)
        return line or self.fallback.on_defiance(advice, action, view)


def _one_sentence(raw):
    """First line, unquoted, trimmed — the model's spoken output, tidied."""
    text = str(raw or "").strip()
    if not text:
        return None
    line = text.splitlines()[0].strip().strip('"').strip()
    return line[:200] or None


def _board_text(board):
    return " ".join(str(c) for c in board) if board else "(nothing yet)"


def build_advice_prompt(view, odds_payload, base):
    hero = view["hero"]
    lines = [
        "Your player: %s. Stack %d." % (hero["name"], hero["stack"]),
        "Their cards: %s" % " ".join(str(c) for c in hero["hole"]),
        "Board: %s   Street: %s   Pot: %d" % (_board_text(view["board"]),
                                              view["street"], view["pot"]),
    ]
    if view["to_call"] > 0:
        lines.append("To call: %d  (pot odds %.0f%% — they must win that often to break even)"
                     % (view["to_call"], base["pot_odds"] * 100))
    else:
        lines.append("Nothing to call — checking is free.")
    if view["can_raise"]:
        lines.append("A raise must be to between %d and %d total this street."
                     % (view["min_raise_to"], view["max_raise_to"]))
    else:
        lines.append("They cannot raise here — only fold, call, or shove.")

    lines.append("")
    lines.append("Simulation vs random hands (%d rollouts): they win %.0f%% (tie %.0f%%)."
                 % (odds_payload["samples"], odds_payload["equity"] * 100,
                    odds_payload["tie"] * 100))
    made = odds_payload.get("made")
    if made:
        lines.append("Holding right now: %s" % made["name"])
    outs = [c for c in odds_payload["categories"] if c["make"] >= 0.02]
    if outs:
        lines.append("Where their equity comes from: " + ", ".join(
            "%s %.0f%% of the time (worth %.0f%% of the pot)"
            % (c["name"], c["make"] * 100, c["win"] * 100) for c in outs[:5]))

    lines.append("")
    lines.append("What each live opponent has DONE this hand, and what a Bayesian "
                 "read of it says they hold:")
    lines.append(format_actions(view["actions"], view["players"], base["reads"]))
    lines.append("")
    if base.get("vs_range"):
        lines.append("Against random hands they win %.0f%%. Re-simulated against the "
                     "ranges above — the hands these opponents are actually "
                     "representing — they win %.0f%%. That second number is the real one."
                     % (base["equity"] * 100, base["adjusted"] * 100))
    else:
        lines.append("They win %.0f%% against random hands (%.0f%% once the read is "
                     "taken into account)." % (base["equity"] * 100, base["adjusted"] * 100))
    lines.append("Your own arithmetic says: %s%s, against a %.0f%% price."
                 % (base["action"],
                    (" to %d" % base["amount"]) if base["amount"] else "",
                    base["pot_odds"] * 100))
    lines.append("Agree or overrule it, but decide. The range percentages above are "
                 "yours to interpret, not to repeat — say what they mean. Respond with "
                 "the JSON object only.")
    return "\n".join(lines)


def format_actions(actions, players, reads=None):
    reads = {r["name"]: r for r in (reads or [])}
    live = {p["name"] for p in players if not p["is_hero"] and not p["folded"]}
    rows = []
    for info in players:
        if info["is_hero"]:
            continue
        mine = [a for a in actions if a["name"] == info["name"]]
        state = "still in" if info["name"] in live else "FOLDED"
        moves = (", ".join("%s: %s" % (a["street"].lower(), a["desc"]) for a in mine)
                 or "nothing yet")
        rows.append("- %s (%s, stack %d): %s"
                    % (info["name"], state, info["stack"], moves))
        read = reads.get(info["name"])
        if read and read.get("buckets"):
            shape = ", ".join("%.0f%% %s" % (b["p"] * 100, b["key"]) for b in read["buckets"])
            row = "    range now: %s" % shape
            if read.get("bluff") is not None:
                row += "  ->  bluffing about %.0f%% of the time" % (read["bluff"] * 100)
            rows.append(row)
    return "\n".join(rows) or "- (nobody has acted yet)"


def build_verdict_prompt(context, tone):
    advice = context.get("advice") or {}
    lines = [
        "Tone you must take: %s" % tone,
        "You told them: %s%s" % (advice.get("action", "(nothing)"),
                                 (" to %d" % advice["amount"]) if advice.get("amount") else ""),
        "Your line at the time: \"%s\"" % (advice.get("line") or ""),
        "They actually: %s" % context["action_desc"],
        "They %s your advice." % ("followed" if context["followed"] else "IGNORED"),
        "Result: %s%d chips on the hand." % ("+" if context["net"] >= 0 else "", context["net"]),
    ]
    if context.get("hero_hand"):
        lines.append("They ended with: %s" % context["hero_hand"])
    if context.get("winner_hand"):
        lines.append("The hand was won with: %s" % context["winner_hand"])
    if context.get("would_have_won") is True:
        lines.append("IMPORTANT: they folded a hand that would have WON the pot.")
    if context.get("right") is False:
        lines.append("Your advice was WRONG. Do not weasel out of it.")
    elif context.get("right") is True:
        lines.append("Your advice was RIGHT.")
    lines.append("")
    lines.append("One sentence, out loud, to them. No quotes.")
    return "\n".join(lines)
