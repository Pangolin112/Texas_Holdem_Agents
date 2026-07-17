"""What is he actually holding — and is he bluffing?

A read like "he's been betting, he's probably strong" is not an answer. This is:
start from every hand the opponent could still have, and let each thing they did
this hand move the odds on each of them.

    P(hand | what they did)  ∝  P(hand)  ×  ∏  P(each action | that hand)

The prior is flat over every two-card combination not already accounted for —
the board, and *your own cards*, which is why holding the ace of spades really
does make his flush less likely. The likelihood is the only place opinion
enters, and it encodes one idea from poker rather than a pile of thresholds:

  * **betting is polarized.** Big bets come from hands strong enough to want the
    money in — and from hands with nothing, which can't win any other way. The
    hands in between mostly don't bet: they have something to lose.
  * **calling is condensed.** Calling is what you do with a hand that's good but
    not good enough to raise.

Run that over each holding and the posterior *is* the range. Sum the weight
sitting on hands that can't currently beat anything and you have the number the
read was really after: **how often is he bluffing right now.**

Each action is scored against the board as it was *at the time* — a bet on the
flop says something about a flop hand, not about the river. And every strength
here is exact: with the board known, "how strong is this holding" is just where
it ranks among every other holding, which is a count, not an estimate.

Nothing in here ever sees an opponent's cards. It reads the betting, the board,
and your own hand — the same things you can see.
"""

from __future__ import annotations

import math
from itertools import combinations, product

from .brains import preflop_strength
from .cards import Card, RANK_VALUES, SUITS
from .evaluator import rank_cards

FULL_DECK = [Card(v, s) for v, s in product(RANK_VALUES.values(), SUITS)]

# Where a holding sits on the 0-1 strength scale. A random hand averages 0.5 by
# construction (strength is a percentile), so that's the line between "weaker
# than a stranger" and "stronger".
BASELINE = 0.50

# How the buckets carve up the range. Order matters: first match wins.
B_STRONG = "strong"      # a hand that wants the money in
B_MEDIUM = "medium"      # top pair-ish: worth something, not worth a war
B_DRAW = "draw"          # can't win now, might by the river
B_WEAK = "weak"          # a bad made hand
B_AIR = "air"            # nothing at all — if this is betting, it's bluffing

STRONG_AT = 0.80
MEDIUM_AT = 0.55
WEAK_AT = 0.30

# --- the behavioural model: the only opinion in the file -------------------
# Deliberately gentle. Every hand keeps some weight on every action, so no
# amount of betting can drive a holding's probability to zero — real people
# turn up with anything, and a range that has convinced itself is worse than
# no range at all.

BLUFF_APPETITE = 0.60    # how often a hand with nothing fires at a small pot
BLUFF_RESTRAINT = 0.15   # ...and how much the bigger bets put it off
VALUE_BAR = 0.45         # the weakest hand that bets for value at all
VALUE_STEEPNESS = 1.0    # how much more a bigger bet demands of a value hand
FLOOR = 0.02             # nobody is ever fully ruled out


def p_aggressive(s, heat):
    """Chance a holding of strength `s` bets/raises `heat` x the pot.

    Two reasons to bet, so two terms. Value rises with strength, and a bigger
    bet demands more of it — only the top of the range wants to put in three
    pots. Bluffs come from the hands that can't win any other way, and get a
    little *rarer* as the bet grows: risking three pots to win one is a worse
    deal than risking a third, and people feel that.

    Polarization falls out of the two moving apart: medium hands stop betting
    long before the bluffs do, so the bigger the bet, the more the range is
    nuts-or-nothing. The constants above are set so that the bluff share of a
    betting range lands near where balanced play says it should — about a third
    of a pot-sized bet, more of an overbet, less of a second barrel. They're
    the one judgement call in the file, and they're all in one place.
    """
    heat = min(2.5, max(0.0, heat))
    value = max(0.0, (s - VALUE_BAR) / (1.0 - VALUE_BAR)) ** (1.0 + VALUE_STEEPNESS * heat)
    bluff = BLUFF_APPETITE / (1.0 + BLUFF_RESTRAINT * heat) * max(0.0, (WEAK_AT - s) / WEAK_AT)
    return min(0.97, FLOOR + 0.9 * value + bluff)


def p_call(s):
    """Calling is condensed: a bump around "good, but not raising"."""
    return min(0.95, FLOOR + 0.9 * math.exp(-((s - 0.60) ** 2) / (2 * 0.17 ** 2)))


def p_check(s):
    """Whatever isn't betting. Weak and medium hands check the most."""
    return max(FLOOR, 1.0 - p_aggressive(s, 0.6))


def action_likelihood(kind, heat, s):
    if kind in ("bet", "raise", "all_in"):
        return p_aggressive(s, heat)
    if kind == "call":
        return p_call(s)
    if kind == "check":
        return p_check(s)
    return 1.0   # blinds and anything else say nothing about a hand


# --- exact strength: where a holding ranks among all the others -------------

def strength_table(combos, board):
    """`combos` scored on `board`: the share of the other holdings each beats.

    Exact, not sampled — with the board known this is a counting problem. Ties
    count half, so a random holding averages 0.5 whatever the street. Preflop
    there's no board to rank against, so it ranks the same holdings by their
    starting-hand value instead: different measure, same scale, so a bucket
    means the same thing before and after the flop.
    """
    if not board:
        ranks = [preflop_strength(list(c)) for c in combos]
    else:
        ranks = [rank_cards(list(c) + board) for c in combos]  # once each, not per compare
    order = sorted(range(len(combos)), key=lambda i: ranks[i])
    out = [0.0] * len(combos)
    total = float(len(combos))
    i = 0
    while i < len(order):
        # Walk the ties together so hands that split get equal strength.
        j = i
        key = ranks[order[i]]
        while j < len(order) and ranks[order[j]] == key:
            j += 1
        s = (i + (j - i) / 2.0) / total
        for k in range(i, j):
            out[order[k]] = s
        i = j
    return out


def has_draw(hole, board):
    """Four to a flush, or four to a straight (gutshots included). Only
    meaningful while there are cards to come."""
    if len(board) < 3 or len(board) >= 5:
        return False
    cards = list(hole) + list(board)
    suits = {}
    for c in cards:
        suits[c.suit] = suits.get(c.suit, 0) + 1
    if any(n == 4 for n in suits.values()):
        return True
    values = {c.value for c in cards}
    if 14 in values:
        values.add(1)   # the wheel
    for low in range(1, 11):
        if len(values & set(range(low, low + 5))) == 4:
            return True
    return False


def bucket_of(s, draw):
    if s >= STRONG_AT:
        return B_STRONG
    if s >= MEDIUM_AT:
        return B_MEDIUM
    if draw:
        return B_DRAW     # a draw is worth more than the pair it isn't
    if s >= WEAK_AT:
        return B_WEAK
    return B_AIR


# --- the estimate -----------------------------------------------------------

def board_at(board, street):
    """The board as it stood when a given street was bet."""
    return {"PREFLOP": [], "FLOP": board[:3], "TURN": board[:4],
            "RIVER": board[:5]}.get(street, board)


def estimate(view, names=None):
    """A posterior over every holding for each live opponent.

    Returns {name: range} where a range carries the weighted combos (so equity
    can be simulated against it), what it's made of, and the bluff number.
    """
    board = list(view["board"])
    dead = set(board) | set(view["hero"]["hole"])
    deck = [c for c in FULL_DECK if c not in dead]
    combos = list(combinations(deck, 2))
    if not combos:
        return {}

    live = [p["name"] for p in view["players"]
            if not p["is_hero"] and not p["folded"]
            and (names is None or p["name"] in names)]
    if not live:
        return {}

    # Strength on the current board is what the buckets mean; the per-street
    # tables are what the betting gets judged against. Both are shared across
    # opponents — same board, same numbers.
    now = strength_table(combos, board)
    draws = [has_draw(c, board) for c in combos]
    tables = {}
    for street in ("PREFLOP", "FLOP", "TURN", "RIVER"):
        then = board_at(board, street)
        if len(then) == len(board):
            tables[street] = now
        elif street == "PREFLOP" or len(then) >= 3:
            tables[street] = strength_table(combos, then)

    out = {}
    for name in live:
        acts = [a for a in view["actions"] if a["name"] == name]
        weights = [1.0] * len(combos)
        for a in acts:
            table = tables.get(a["street"])
            if table is None:
                continue
            heat = a["amount"] / float(max(1, a["pot"]))
            for i in range(len(combos)):
                weights[i] *= action_likelihood(a["kind"], heat, table[i])
        total = sum(weights)
        if total <= 0:
            weights = [1.0] * len(combos)
            total = float(len(combos))
        weights = [w / total for w in weights]

        buckets = {}
        mean = 0.0
        for i, w in enumerate(weights):
            mean += w * now[i]
            key = bucket_of(now[i], draws[i])
            buckets[key] = buckets.get(key, 0.0) + w

        last_aggressive = bool(acts and acts[-1]["kind"] in ("bet", "raise", "all_in"))
        out[name] = {
            "name": name,
            "combos": combos,
            "weights": weights,
            "cum": _cumulative(weights),
            "mean_strength": mean,
            "buckets": [{"key": k, "p": buckets[k]}
                        for k in sorted(buckets, key=lambda k: -buckets[k])],
            # "Bluffing" only means anything about someone who is betting. A
            # checker isn't bluffing, they're just there.
            "bluff": buckets.get(B_AIR, 0.0) if last_aggressive else None,
            "semi_bluff": buckets.get(B_DRAW, 0.0) if last_aggressive else None,
            "last_aggressive": last_aggressive,
            "actions": len(acts),
        }
    return out


def _cumulative(weights):
    out = []
    running = 0.0
    for w in weights:
        running += w
        out.append(running)
    return out


def sample_hand(range_, used, rng, tries=32):
    """One holding drawn from the posterior, skipping cards already dealt.

    Rejecting collisions is exactly sampling the posterior restricted to what's
    left. Returns None if it can't find one, and the caller falls back to a
    random hand rather than looping forever.
    """
    combos, cum = range_["combos"], range_["cum"]
    if not cum:
        return None
    top = cum[-1]
    lo_hint = 0
    for _ in range(tries):
        target = rng.random() * top
        i = _bisect(cum, target, lo_hint)
        if i >= len(combos):
            i = len(combos) - 1
        a, b = combos[i]
        if a not in used and b not in used:
            return a, b
    return None


def _bisect(cum, target, lo=0):
    hi = len(cum)
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo
