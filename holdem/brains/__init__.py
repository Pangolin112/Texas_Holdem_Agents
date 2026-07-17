"""Decision-making for AI seats.

LLMBrain asks an OpenAI model for a JSON decision built from everything the
agent may legitimately know: its own hole cards, the board, pot, stacks, the
full action history, table talk, and results of previous hands. It never sees
anyone else's hole cards. If the API call fails, HeuristicBrain takes over so
the game keeps moving.
"""

from __future__ import annotations

from .model_chain import ModelChain, build_model_chain, DEEPSEEK_FALLBACKS, _is_model_error
from .personalities import PERSONALITIES, LANGUAGE_NOTES, _lang_note
from .policy import _softmax, PolicyBrain, preflop_strength
from .heuristic import HeuristicBrain
from .prompts import (SYSTEM_TEMPLATE, CHAT_SYSTEM_TEMPLATE, EXPLAIN_SYSTEM_TEMPLATE,
                      BUY_SYSTEM_TEMPLATE, format_chat, format_history, build_user_prompt)
from .speech import _blocked, spoken_action, reconcile_action
from .llm import ModelCaller, LLMBrain

__all__ = [
    "ModelChain", "build_model_chain", "DEEPSEEK_FALLBACKS", "_is_model_error",
    "PERSONALITIES", "LANGUAGE_NOTES", "_lang_note",
    "_softmax", "PolicyBrain", "preflop_strength",
    "HeuristicBrain",
    "SYSTEM_TEMPLATE", "CHAT_SYSTEM_TEMPLATE", "EXPLAIN_SYSTEM_TEMPLATE",
    "BUY_SYSTEM_TEMPLATE", "format_chat", "format_history", "build_user_prompt",
    "_blocked", "spoken_action", "reconcile_action",
    "ModelCaller", "LLMBrain",
]
