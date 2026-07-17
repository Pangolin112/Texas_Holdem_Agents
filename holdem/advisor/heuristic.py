"""HeuristicAdvisor: your equity against their range, against the price. No
API, no waiting — and what the LLM advisor falls back to on any API hiccup."""

from __future__ import annotations

from .. import odds, ranges
from ..players import ALL_IN, CALL, CHECK, FOLD, RAISE
from .constants import (RANGE_EQUITY_BUDGET, TONE_HUMBLED, TONE_SHRUG,
                        TONE_TOLD_YOU, TONE_VINDICATED, GRADE_LOOSE_CALL,
                        GRADE_MISSED_VALUE, GRADE_SCARED_FOLD, GRADE_WILD_RAISE)
from .reads import danger_level, discount_equity, pot_odds, read_opponents, threat_level


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
        threat = threat_level(reads)
        return {
            "action": action,
            "amount": amount,
            "key": key,
            "confidence": round(confidence, 2),
            "equity": round(equity, 4),
            "adjusted": round(adjusted, 4),
            "pot_odds": round(price, 4),
            "threat": round(threat, 3),
            # The spot's color, 0 (white, all clear) .. 4 (purple, get out).
            # Derived from the numbers, so the LLM overruling the action in
            # _merge doesn't change it — danger describes the spot, not the plan.
            "danger": danger_level(adjusted, price, threat, to_call),
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

    # -- the send-off ------------------------------------------------------

    SEND_OFFS = {
        "no_hands": ("Didn't even play a hand. Possibly the wisest line all night.",
                     "一手没打就走——可能是今晚最明智的一手。"),
        "big_win": ("You ran over this table tonight. Come back before they forget how.",
                    "你今晚把这桌打穿了。趁他们还没缓过来,记得回来。"),
        "win": ("You leave ahead. That's the whole job — don't let anyone complicate it.",
                "带着盈利离场。这就是打牌的全部目标,别让任何人把它复杂化。"),
        "even": ("Flat. Cheaper than most poker lessons, and you got the lessons anyway.",
                 "不输不赢。比大多数学费便宜,课倒是一节没少上。"),
        "loss": ("Tonight cost you. The ledger says why — and it isn't the cards.",
                 "今晚交了学费。原因账本上写着,不在牌上。"),
        "big_loss": ("Rough night. Read the ledger before you blame the deck.",
                     "今晚很不顺。怪牌之前,先把账本看一遍。"),
    }

    def send_off(self, payload):
        """The closing statement as the player stands up: the night in one
        line, plus the habit — the same one the debriefs kept booking."""
        hands = payload.get("hands") or 0
        if hands <= 0:
            key = "no_hands"
        else:
            frac = payload["net"] / float(max(1, payload.get("starting_stack") or 1))
            if frac >= 0.5:
                key = "big_win"
            elif payload["net"] > 0:
                key = "win"
            elif frac <= -0.5:
                key = "big_loss"
            elif payload["net"] < 0:
                key = "loss"
            else:
                key = "even"
        en, zh = self.SEND_OFFS[key]
        line = zh if self.lang == "zh" else en
        tail = self._session_line(payload.get("session") or {"hands": 0})
        return line + (" " + tail if tail else "")

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

    # -- the debrief -------------------------------------------------------

    REVIEW_LINES = {
        GRADE_SCARED_FOLD: (
            "You folded getting the right price — that's the mistake I mind most.",
            "价格明明合适你却弃了——这种错我最在意。"),
        GRADE_LOOSE_CALL: (
            "You paid for cards the price didn't justify. That's where the chips go.",
            "这个价不值,你还是跟了。筹码就是这么漏掉的。"),
        GRADE_WILD_RAISE: (
            "You raised into a range that had you beat.",
            "明明落后还去加注,这是给人送钱。"),
        GRADE_MISSED_VALUE: (
            "Best hand at the table and you let them see cards for free.",
            "拿着最好的牌却让他们免费看牌,亏的是本该赢的钱。"),
    }
    REVIEW_CLEAN = [
        ("Clean hand. Every decision was right by the numbers.", "这手打得干净,每个决定都对得起数字。"),
        ("Nothing to fix there. Do it again.", "没什么可挑的,下次还这么打。"),
    ]
    SESSION_LINES = {
        "loose": ("Same leak as before: you call too much.", "还是老毛病:你跟得太松。"),
        "scared": ("You keep folding hands the price says to play. Trust the maths.",
                   "你总把该打的牌弃掉。相信赔率。"),
        "defiance_costs": ("And the record says it plainly: the hands where you ignore me "
                           "are the ones costing you.",
                           "而且账本摆在这:不听劝的那些手,正是在亏钱的手。"),
    }

    def review(self, ctx):
        """The whole hand in one or two spoken sentences: the worst process
        mistake if there was one, praise if there wasn't, and the session-long
        habit when the record actually shows one."""
        graded = [r for r in ctx["decisions"] if r["grade"]]
        if graded:
            en, zh = self.REVIEW_LINES[graded[-1]["grade"]]
        else:
            en, zh = self.rng.choice(self.REVIEW_CLEAN)
        line = zh if self.lang == "zh" else en
        tail = self._session_line(ctx["session"])
        return line + (" " + tail if tail else "")

    def _session_line(self, s):
        """One sentence about the pattern — only when there is enough of one.
        A habit needs evidence; two hands of anything is a coincidence."""
        if s["hands"] < 5:
            return None
        key = None
        mistakes = s.get("mistakes") or {}
        if mistakes.get(GRADE_LOOSE_CALL, 0) >= 3:
            key = "loose"
        elif mistakes.get(GRADE_SCARED_FOLD, 0) >= 3:
            key = "scared"
        elif (s["decisions"] >= 6
              and s["followed"] < 0.5 * s["decisions"]
              and s["net_defied"] < s["net_followed"]):
            key = "defiance_costs"
        if key is None:
            return None
        en, zh = self.SESSION_LINES[key]
        return zh if self.lang == "zh" else en
