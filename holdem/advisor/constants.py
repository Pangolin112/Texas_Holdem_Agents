"""Module-level vocabulary shared across the advisor package: the coach's
identity, the fixed small set of read/tone/grade labels, and their strength
priors. Front-ends turn these keys into (localized) text."""

from __future__ import annotations

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

# Process grades for the debrief: was the MOVE right by the numbers at the
# time, regardless of how the cards fell. None means nothing to criticize.
GRADE_SCARED_FOLD = "scared_fold"    # folded although the price was right
GRADE_LOOSE_CALL = "loose_call"      # paid a price the equity didn't justify
GRADE_WILD_RAISE = "wild_raise"      # raised while clearly behind
GRADE_MISSED_VALUE = "missed_value"  # best hand, checked it anyway

GRADE_WORDS = {
    GRADE_SCARED_FOLD: "scared fold (the price was right)",
    GRADE_LOOSE_CALL: "loose call (priced out)",
    GRADE_WILD_RAISE: "raised while behind",
    GRADE_MISSED_VALUE: "missed value (a bet was owed)",
}
