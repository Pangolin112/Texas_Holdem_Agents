"""Small shared bits: the .env loader, model defaults, JSON serialization of
engine objects, and the quit sentinel shared by the session queues."""

from __future__ import annotations

import os
import re

from holdem.cards import RED_SUITS, SUIT_SYMBOLS, VALUE_CHARS, VALUE_LABELS

# Same model defaults as the terminal entry point.
DEFAULT_MODEL = "gpt-5.2"
FALLBACK_MODELS = ["gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-4o-mini"]
OPENAI_MODEL_SUGGESTIONS = list(FALLBACK_MODELS)
DEEPSEEK_MODEL_SUGGESTIONS = ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"]

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(HERE, "static")

_QUIT = object()  # sentinel pushed onto the input queue to end a blocked wait


# --------------------------------------------------------------------------- #
# .env loader (identical to main.py — kept dependency-free)
# --------------------------------------------------------------------------- #

def load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def server_config():
    """Defaults the setup screen should show (from .env / host env)."""
    chosen = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    base_url = os.environ.get("OPENAI_BASE_URL")
    on_deepseek = bool(base_url and "deepseek" in base_url) or chosen.startswith("deepseek")
    provider = "DeepSeek" if on_deepseek else "OpenAI"
    return {
        "model": chosen,
        "provider": provider,
        "has_api_key": bool(os.environ.get("OPENAI_API_KEY")),
        "model_suggestions": (DEEPSEEK_MODEL_SUGGESTIONS if on_deepseek
                              else OPENAI_MODEL_SUGGESTIONS),
    }


# --------------------------------------------------------------------------- #
# Serialization: engine objects -> JSON-safe dicts for the browser
# --------------------------------------------------------------------------- #

def card_data(card):
    """A card the browser can draw: display rank, suit glyph, color, code."""
    return {
        "rank": VALUE_LABELS[card.value],       # "10", "K", "A"
        "suit": card.suit,                       # s h d c
        "symbol": SUIT_SYMBOLS[card.suit],       # the pip
        "red": card.suit in RED_SUITS,
        "code": VALUE_CHARS[card.value] + card.suit,
    }


def cards_data(cards):
    return [card_data(c) for c in cards]


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text):
    return _ANSI.sub("", str(text))
