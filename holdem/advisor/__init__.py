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

from ..players import ALL_IN, CALL, CHECK, FOLD, RAISE, advice_action  # noqa: F401
from .constants import (ADVISOR, BASELINE, GRADE_LOOSE_CALL, GRADE_MISSED_VALUE,
                        GRADE_SCARED_FOLD, GRADE_WILD_RAISE, GRADE_WORDS,
                        RANGE_EQUITY_BUDGET, READ_AGGRESSIVE, READ_CALLING,
                        READ_PASSIVE, READ_POLARIZED, READ_QUIET, READ_SHOVED,
                        READ_STRENGTH, READ_STRONG, TONE_HUMBLED, TONE_SHRUG,
                        TONE_TOLD_YOU, TONE_VINDICATED)
from .reads import (advice_command, danger_level, discount_equity,
                    followed_advice, grade_decision, pot_odds, read_opponents,
                    threat_level, _round)
from .heuristic import HeuristicAdvisor, verdict_tone
from .prompts import (ADVISE_SYSTEM, DEFIANCE_SYSTEM, REVIEW_SYSTEM,
                      SEND_OFF_SYSTEM, VERDICT_SYSTEM, _board_text,
                      _one_sentence, build_advice_prompt, build_review_prompt,
                      build_verdict_prompt, format_actions)
from .llm import LLMAdvisor

__all__ = [
    "ALL_IN", "CALL", "CHECK", "FOLD", "RAISE", "advice_action",
    "ADVISOR", "BASELINE", "GRADE_LOOSE_CALL", "GRADE_MISSED_VALUE",
    "GRADE_SCARED_FOLD", "GRADE_WILD_RAISE", "GRADE_WORDS",
    "RANGE_EQUITY_BUDGET", "READ_AGGRESSIVE", "READ_CALLING", "READ_PASSIVE",
    "READ_POLARIZED", "READ_QUIET", "READ_SHOVED", "READ_STRENGTH",
    "READ_STRONG", "TONE_HUMBLED", "TONE_SHRUG", "TONE_TOLD_YOU",
    "TONE_VINDICATED",
    "advice_command", "danger_level", "discount_equity", "followed_advice",
    "grade_decision", "pot_odds", "read_opponents", "threat_level",
    "HeuristicAdvisor", "verdict_tone",
    "ADVISE_SYSTEM", "DEFIANCE_SYSTEM", "REVIEW_SYSTEM", "SEND_OFF_SYSTEM",
    "VERDICT_SYSTEM", "build_advice_prompt", "build_review_prompt",
    "build_verdict_prompt", "format_actions",
    "LLMAdvisor",
]
