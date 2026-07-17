"""Keeping words honest: a player may lie about their CARDS, but if their spoken
line names the move they're making, the actual move must match it."""

from __future__ import annotations

import re

from ..players import Action, FOLD, CHECK, CALL, RAISE, ALL_IN

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
