"""The model chain: a preferred model plus fallbacks, with automatic downgrade."""

from __future__ import annotations


class ModelChain:
    """A preferred model plus fallbacks. If the chosen model isn't available on
    the account, the game steps down to the next one instead of breaking. One
    shared instance is passed to every seat so a downgrade happens only once."""

    def __init__(self, models):
        seen = []
        for m in models:
            if m and m not in seen:
                seen.append(m)
        self.models = seen or ["gpt-5-mini"]
        self.idx = 0

    @property
    def current(self):
        return self.models[self.idx]

    def downgrade(self):
        if self.idx < len(self.models) - 1:
            self.idx += 1
            return True
        return False


# DeepSeek's OpenAI-compatible endpoint only serves deepseek-* models, so a table
# pointed at it must fall back *within* that family — never to a gpt-* id that the
# endpoint doesn't have.
DEEPSEEK_FALLBACKS = ["deepseek-chat", "deepseek-reasoner"]


def build_model_chain(chosen, base_url=None, openai_fallbacks=None):
    """Preferred model first, then provider-matched fallbacks. DeepSeek is
    detected from the endpoint or the model id, so a downgrade never jumps to a
    model the current endpoint can't serve."""
    on_deepseek = (base_url and "deepseek" in base_url) or chosen.startswith("deepseek")
    fallbacks = DEEPSEEK_FALLBACKS if on_deepseek else (openai_fallbacks or [])
    return ModelChain([chosen] + list(fallbacks))


def _is_model_error(exc):
    """True if the exception looks like 'this model doesn't exist / no access'
    (as opposed to a transient network or parameter problem)."""
    if "notfound" in type(exc).__name__.lower():
        return True
    msg = str(exc).lower()
    return "model" in msg and any(s in msg for s in (
        "not found", "does not exist", "unknown", "invalid", "no access",
        "not available", "deprecated"))
