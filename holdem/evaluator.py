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
