"""Difficulty tiers for the LLM seats: how much experience a seat gets to use.

One model plays every seat (and stands behind the coach) — what separates a
casual player from a shark isn't a different brain, it's what's in front of it:
how much of the session it remembers, whether it keeps a book on how everyone
plays, and whether it works out the price of a call. Levels gate exactly that.
"""

from __future__ import annotations

SKILL_LEVELS = {
    "casual": {
        "key": "casual",
        "profiles": False,   # keeps no book on the other players
        "memory": 2,         # remembers only the last couple of hands
        "pot_odds": False,   # never works out the price of a call
        "effort": "low",
        "note": "\n\nTonight you're playing loose and casual: you go by feel, "
                "not arithmetic. You never work out pot odds or precise ranges "
                "— you look at your cards, the board and the people, and do "
                "what feels right, even when it isn't the textbook move.",
    },
    "standard": {
        "key": "standard",
        "profiles": True,
        "memory": 5,
        "pot_odds": True,
        "effort": "low",
        "note": "",
    },
    "shark": {
        "key": "shark",
        "profiles": True,
        "memory": 8,
        "pot_odds": True,
        "effort": "medium",
        "note": "\n\nYou are a genuinely strong, experienced player. Think in "
                "ranges, not single hands; weigh position, stack-to-pot ratio "
                "and what your line represents; attack weakness and respect "
                "real strength. Use everything you've seen of each player "
                "tonight to exploit exactly how they play. Stay in character, "
                "but play sharp.",
    },
}


def skill_level(name):
    """The named level's config, defaulting to standard for anything unknown."""
    if isinstance(name, dict):
        return name
    return SKILL_LEVELS.get(str(name or "").lower(), SKILL_LEVELS["standard"])
