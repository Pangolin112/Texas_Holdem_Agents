"""Pure functions: reading opponents from their betting, pricing the spot, and
grading what the player actually did against the numbers at the time."""

from __future__ import annotations

from ..players import ALL_IN, CALL, CHECK, FOLD, RAISE
from .constants import (BASELINE, READ_AGGRESSIVE, READ_CALLING, READ_PASSIVE,
                        READ_POLARIZED, READ_QUIET, READ_SHOVED, READ_STRENGTH,
                        READ_STRONG, GRADE_LOOSE_CALL, GRADE_MISSED_VALUE,
                        GRADE_SCARED_FOLD, GRADE_WILD_RAISE)


def grade_decision(advice, action):
    """Judge what the player actually did against the numbers it was done
    against — process, not results. A good call that lost money is still a
    good call, and this is the function that knows it.

    Deliberately generous: only clear breaches get a grade, because a debrief
    that nitpicks every marginal choice teaches the player to close the panel.
    """
    if action is None or not advice:
        return None
    kind = action.kind
    tier = advice.get("preflop_tier")
    if tier is not None:
        # Preflop is graded on the starting hand's tier — the same yardstick
        # the advice itself used, because multiway equity vs random hands
        # would book every correct preflop defend as a "loose call".
        cost = advice.get("preflop_cost") or 0.0
        if advice["to_call"] > 0:
            if kind == FOLD and (tier == 3 or (tier == 2 and cost <= 4)):
                return GRADE_SCARED_FOLD
            if kind == CALL and tier == 0 and cost > 1:
                return GRADE_LOOSE_CALL
            if kind in (RAISE, ALL_IN) and tier == 0:
                return GRADE_WILD_RAISE
        return None
    margin = advice["adjusted"] - advice["pot_odds"]
    if advice["to_call"] > 0:
        if kind == FOLD and margin >= 0.08:
            return GRADE_SCARED_FOLD
        if kind == CALL and margin <= -0.05:
            return GRADE_LOOSE_CALL
        if kind in (RAISE, ALL_IN) and margin <= -0.08:
            return GRADE_WILD_RAISE
    else:
        if kind == CHECK and advice["action"] in (RAISE, ALL_IN) \
                and advice["adjusted"] >= 0.70:
            return GRADE_MISSED_VALUE
    return None


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


def danger_level(adjusted, price, threat, to_call):
    """How scary this spot is, 0..4 — the color scale behind the coach panel
    (white, green, blue, red, purple; each step more dangerous).

    Danger describes the SPOT, not the recommendation: how far your equity
    against their ranges sits from the price you're being asked to pay, with a
    one-step bump when someone's range is genuinely monstrous. When checking is
    free it caps at "close" — a weak hand with nothing to pay is weak, not in
    danger, and a panel that cries wolf on every bad flop teaches the player to
    ignore it.
    """
    if to_call <= 0:
        if adjusted >= 0.65 and threat < 0.75:
            return 0
        if adjusted >= 0.50:
            return 1
        return 2
    margin = adjusted - price
    bump = 1 if threat >= 0.85 else 0
    if margin >= 0.20 and not bump:
        return 0
    if margin >= 0.08:
        return 1 + bump
    if margin >= -0.05:
        return 2 + bump
    if margin >= -0.18:
        return min(4, 3 + bump)
    return 4


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
