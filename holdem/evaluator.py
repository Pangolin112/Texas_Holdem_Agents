"""Poker hand evaluation: best 5-card hand out of 5-7 cards.

A hand rank is a tuple; bigger tuples are better hands. The first element is
the category (8 = straight flush ... 0 = high card), the rest are tiebreakers.
"""

from collections import Counter
from itertools import combinations

from .cards import VALUE_NAMES, plural

STRAIGHT_FLUSH = 8
FOUR_OF_A_KIND = 7
FULL_HOUSE = 6
FLUSH = 5
STRAIGHT = 4
THREE_OF_A_KIND = 3
TWO_PAIR = 2
PAIR = 1
HIGH_CARD = 0

# Short label per category, for the odds table (hand_name below writes the full
# phrase, kickers and all, for a hand that actually exists).
CATEGORY_NAMES = {
    STRAIGHT_FLUSH: "Straight Flush",
    FOUR_OF_A_KIND: "Four of a Kind",
    FULL_HOUSE: "Full House",
    FLUSH: "Flush",
    STRAIGHT: "Straight",
    THREE_OF_A_KIND: "Three of a Kind",
    TWO_PAIR: "Two Pair",
    PAIR: "Pair",
    HIGH_CARD: "High Card",
}


def evaluate_five(cards):
    """Rank exactly five cards."""
    values = sorted((c.value for c in cards), reverse=True)
    is_flush = len({c.suit for c in cards}) == 1

    unique = sorted(set(values), reverse=True)
    straight_high = 0
    if len(unique) == 5:
        if unique[0] - unique[4] == 4:
            straight_high = unique[0]
        elif unique == [14, 5, 4, 3, 2]:  # the wheel: A-2-3-4-5
            straight_high = 5

    # Groups of equal ranks, biggest group first, then highest rank.
    groups = sorted(Counter(values).items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if is_flush and straight_high:
        return (STRAIGHT_FLUSH, straight_high)
    if groups[0][1] == 4:
        return (FOUR_OF_A_KIND, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] >= 2:
        return (FULL_HOUSE, groups[0][0], groups[1][0])
    if is_flush:
        return tuple([FLUSH] + values)
    if straight_high:
        return (STRAIGHT, straight_high)
    if groups[0][1] == 3:
        kickers = [v for v in values if v != groups[0][0]]
        return tuple([THREE_OF_A_KIND, groups[0][0]] + kickers)
    if groups[0][1] == 2 and groups[1][1] == 2:
        return (TWO_PAIR, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2:
        kickers = [v for v in values if v != groups[0][0]]
        return tuple([PAIR, groups[0][0]] + kickers)
    return tuple([HIGH_CARD] + values)


def best_hand(cards):
    """Best 5-card hand from 5-7 cards. Returns (rank_tuple, best_five_cards)."""
    best_rank = None
    best_five = None
    for combo in combinations(cards, 5):
        rank = evaluate_five(combo)
        if best_rank is None or rank > best_rank:
            best_rank, best_five = rank, combo
    return best_rank, list(best_five)


# --------------------------------------------------------------------------- #
# Fast path: rank 5-7 cards without trying all 21 combinations.
#
# `best_hand` is the readable one and it also hands back the five cards that
# played, which is what the table shows. The odds simulator, though, ranks
# every seat on every rollout and never needs the cards back — so it goes
# through `rank_cards`, which reads the hand straight off rank/suit counts.
# The two agree exactly: test_game.py checks them against each other over
# random deals, which is what lets this live next to the obvious version.
# --------------------------------------------------------------------------- #

def _straight_high(values):
    """Highest card of the best straight in `values` (distinct, descending);
    0 if there's no straight. Scanning downward means the first run of five
    found is already the best one."""
    run = 1
    for i in range(1, len(values)):
        if values[i] == values[i - 1] - 1:
            run += 1
            if run == 5:
                return values[i] + 4
        else:
            run = 1
    if values[0] == 14 and values[-4:] == [5, 4, 3, 2]:
        return 5  # the wheel: the ace drops to the bottom
    return 0


def _group_key(item):
    value, count = item
    return (count, value)


def rank_cards(cards):
    """Rank the best five of 5-7 cards, returning only the rank tuple.

    Same tuple `best_hand` would return, minus the cards themselves.
    """
    counts = {}
    suit_counts = {}
    for c in cards:
        counts[c.value] = counts.get(c.value, 0) + 1
        suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1

    flush_values = None
    for suit, n in suit_counts.items():
        if n >= 5:  # with seven cards at most one suit can reach five
            flush_values = sorted((c.value for c in cards if c.suit == suit),
                                  reverse=True)
            high = _straight_high(flush_values)
            if high:
                return (STRAIGHT_FLUSH, high)
            break

    groups = sorted(counts.items(), key=_group_key, reverse=True)
    top_value, top_count = groups[0]

    if top_count == 4:
        return (FOUR_OF_A_KIND, top_value,
                max(v for v in counts if v != top_value))
    if top_count == 3 and groups[1][1] >= 2:
        # A second trip counts as the pair — only two of it can play.
        return (FULL_HOUSE, top_value, groups[1][0])
    if flush_values is not None:
        return tuple([FLUSH] + flush_values[:5])

    values = sorted(counts, reverse=True)  # distinct ranks, high to low
    high = _straight_high(values)
    if high:
        return (STRAIGHT, high)
    if top_count == 3:
        return (THREE_OF_A_KIND, top_value) + tuple(v for v in values if v != top_value)[:2]
    if top_count == 2 and groups[1][1] == 2:
        second = groups[1][0]
        return (TWO_PAIR, top_value, second,
                max(v for v in counts if v != top_value and v != second))
    if top_count == 2:
        return (PAIR, top_value) + tuple(v for v in values if v != top_value)[:3]
    return tuple([HIGH_CARD] + values[:5])


def starting_hand(hole):
    """The shape of two hole cards, before there's any five-card hand to name.

    Preflop there's nothing to evaluate yet, but "pocket nines" or "ace-king
    suited" is what a player is actually holding in their head — so that's what
    the table shows until the flop lands.
    """
    if len(hole) != 2:
        return None
    high, low = sorted(hole, key=lambda c: -c.value)
    if high.value == low.value:
        return {"kind": "pair", "name": "Pocket %s" % plural(high.value)}
    kind = "suited" if high.suit == low.suit else "offsuit"
    return {"kind": kind, "name": "%s-%s %s" % (VALUE_NAMES[high.value],
                                                VALUE_NAMES[low.value], kind)}


def hand_name(rank):
    cat = rank[0]
    if cat == STRAIGHT_FLUSH:
        if rank[1] == 14:
            return "a Royal Flush"
        return "a Straight Flush, %s high" % VALUE_NAMES[rank[1]]
    if cat == FOUR_OF_A_KIND:
        return "Four of a Kind, %s" % plural(rank[1])
    if cat == FULL_HOUSE:
        return "a Full House, %s over %s" % (plural(rank[1]), plural(rank[2]))
    if cat == FLUSH:
        return "a Flush, %s high" % VALUE_NAMES[rank[1]]
    if cat == STRAIGHT:
        return "a Straight, %s high" % VALUE_NAMES[rank[1]]
    if cat == THREE_OF_A_KIND:
        return "Three of a Kind, %s" % plural(rank[1])
    if cat == TWO_PAIR:
        return "Two Pair, %s and %s" % (plural(rank[1]), plural(rank[2]))
    if cat == PAIR:
        return "a Pair of %s" % plural(rank[1])
    return "High Card, %s" % VALUE_NAMES[rank[1]]
