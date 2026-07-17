"""Live odds for the human seat: what can I still make, and does it win?

Both questions come out of one Monte-Carlo pass. Each rollout deals the missing
board and every live opponent's hole cards from the cards that are genuinely
unknown, ranks everyone with `evaluator.rank_cards`, and books the result under
the category hero *ended* with. So the table reads as a decomposition:

    Flush        make 31%   win 27%
    Two Pair     make 28%   win  9%
    ...                     ─────────
                            total 44%   <- the same number, split by how you get there

which is the honest way to answer "I'm drawing at a few things at once — where
do I actually stand?". A category's win column is its share of total equity,
not its odds of winning *given* you make it: summing the column is the point.

Ties split the pot, so they're booked as a fractional win (1/N for an N-way
chop) — that makes the total match the equity you'd actually realize.

Accuracy is bounded by wall-clock, not by a fixed sample count: the caller
gives a time budget, we report how many rollouts fit. On a river spot with one
opponent that's tens of thousands (the answer is essentially exact); preflop
against five it's a few thousand, good to well under a percent.
"""

import random
import time
from itertools import product

from . import ranges as ranges_mod
from .cards import Card, RANK_VALUES, SUITS
from .evaluator import (CATEGORY_NAMES, best_hand, hand_name, rank_cards,
                        starting_hand)

FULL_DECK = [Card(v, s) for v, s in product(RANK_VALUES.values(), SUITS)]

MAX_SAMPLES = 20000
TIME_BUDGET = 0.22   # seconds; the player is waiting on this


def hand_odds(hole, board, opponents, rng=None, max_samples=MAX_SAMPLES,
              time_budget=TIME_BUDGET, ranges=None):
    """Equity and per-category chances for `hole` against `opponents` hands.

    By default the opponents are dealt at random, which is the number every
    published equity is quoted against and the honest baseline when you know
    nothing. Pass `ranges` (a list of estimates from holdem/ranges.py, one per
    opponent) and each rollout instead deals them a hand drawn from what their
    betting says they have — the same simulation, against real opponents rather
    than strangers.

    Returns a JSON-safe dict (see module docstring).
    """
    rng = rng if rng is not None else random.Random()
    hole = list(hole)
    board = list(board)
    opponents = max(1, int(opponents))
    ranges = list(ranges) if ranges else None

    known = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in known]
    need_board = 5 - len(board)
    need = need_board + 2 * opponents
    if len(hole) < 2 or need_board < 0 or need > len(deck):
        return None

    # What you're holding right now: a real five-card hand once the board can
    # make one, and before that the preflop shape — never nothing.
    if len(hole) + len(board) >= 5:
        rank, five = best_hand(hole + board)
        made = {"cat": rank[0], "name": hand_name(rank), "cards": five,
                "preflop": False}
    else:
        shape = starting_hand(hole)
        made = None if shape is None else {
            "cat": None, "name": shape["name"], "kind": shape["kind"],
            "cards": list(hole), "preflop": True,
        }

    make_counts = {}
    win_shares = {}
    wins = ties = 0
    equity = 0.0
    samples = 0
    sample = rng.sample
    deadline = time.monotonic() + time_budget

    while samples < max_samples:
        # Checking the clock every rollout would cost more than the rollout.
        if samples % 128 == 0 and samples and time.monotonic() > deadline:
            break
        if ranges is None:
            drawn = sample(deck, need)
            full_board = board + drawn[:need_board]
            hands = [(drawn[i], drawn[i + 1])
                     for i in range(need_board, need, 2)]
        else:
            # Deal the opponents from their ranges FIRST, then run the board out
            # of what's left — otherwise a range could want a card the river
            # already took.
            used = set(hole) | set(board)
            hands = []
            for k in range(opponents):
                pair = None
                if k < len(ranges) and ranges[k]:
                    pair = ranges_mod.sample_hand(ranges[k], used, rng)
                if pair is None:   # no range, or it couldn't find a free combo
                    pair = tuple(sample([c for c in deck if c not in used], 2))
                used.update(pair)
                hands.append(pair)
            left = [c for c in deck if c not in used]
            full_board = board + (sample(left, need_board) if need_board else [])

        hero = rank_cards(hole + full_board)
        cat = hero[0]
        make_counts[cat] = make_counts.get(cat, 0) + 1

        tied = 0
        beaten = False
        for pair in hands:
            opp = rank_cards([pair[0], pair[1]] + full_board)
            if opp > hero:
                beaten = True   # one better hand is enough — stop ranking
                break
            if opp == hero:
                tied += 1
        samples += 1
        if beaten:
            continue
        share = 1.0 / (tied + 1)          # an N-way chop pays 1/N
        if tied:
            ties += 1
        else:
            wins += 1
        equity += share
        win_shares[cat] = win_shares.get(cat, 0.0) + share

    if not samples:
        return None

    categories = []
    for cat in sorted(make_counts, reverse=True):
        categories.append({
            "cat": cat,
            "name": CATEGORY_NAMES[cat],
            "make": make_counts[cat] / float(samples),
            "win": win_shares.get(cat, 0.0) / float(samples),
        })

    return {
        "samples": samples,
        "opponents": opponents,
        "street_cards": len(board),
        "made": made,
        "win": wins / float(samples),
        "tie": ties / float(samples),
        "lose": (samples - wins - ties) / float(samples),
        "equity": equity / float(samples),
        "vs_range": ranges is not None,
        "categories": categories,
        # No unknown board cards left: the only thing simulated is which hands
        # the opponents hold, so hero's own category is already decided.
        "final": need_board == 0,
    }
