"""LLMAdvisor: the coach with a model behind it. Falls straight back to
arithmetic on any API or parse failure, so the panel never goes blank mid-hand."""

from __future__ import annotations

import json
import re

from .. import ui
from ..brains import ModelCaller, _lang_note
from ..players import ALL_IN, CALL, CHECK, FOLD, RAISE
from .constants import ADVISOR, GRADE_WORDS, RANGE_EQUITY_BUDGET
from .heuristic import HeuristicAdvisor, verdict_tone
from .prompts import (ADVISE_SYSTEM, DEFIANCE_SYSTEM, REVIEW_SYSTEM,
                      SEND_OFF_SYSTEM, VERDICT_SYSTEM, _board_text,
                      _one_sentence, build_advice_prompt, build_review_prompt,
                      build_verdict_prompt)


class LLMAdvisor(ModelCaller):
    """The coach with a model behind it. Falls straight back to arithmetic on
    any API or parse failure, so the panel never goes blank mid-hand."""

    is_llm = True

    def __init__(self, client, model, rng, lang="en",
                 range_budget=RANGE_EQUITY_BUDGET):
        super().__init__(client, model)
        self.rng = rng
        self.lang = lang
        self.fallback = HeuristicAdvisor(rng, lang, range_budget)
        self._warned = False

    def advise(self, view, odds_payload):
        base = self.fallback.advise(view, odds_payload)
        if self.client is None:
            return base
        ui.thinking(ADVISOR["name"])
        try:
            # _merge stays INSIDE the try: the model can hand back junk in any
            # field ("raise_to": "about 600"), and a coach that can't parse its
            # own thought must shrug and advise on instinct — never take the
            # whole table down through the betting loop.
            data = self._ask_advice(view, odds_payload, base)
            return self._merge(base, data, view)
        except Exception as exc:
            if not self._warned:
                ui.warn("the coach's uplink glitched (%s: %s) — advising on instinct."
                        % (type(exc).__name__, str(exc)[:100]))
                self._warned = True
            return base

    def _merge(self, base, data, view):
        """Take the model's call, but keep it legal and keep the arithmetic —
        the numbers are ours, only the judgement and the words are the model's."""
        kind = str(data.get("action", "")).strip().lower()
        if kind not in (FOLD, CHECK, CALL, RAISE, ALL_IN):
            return base
        if kind == FOLD and view["to_call"] <= 0:
            kind = CHECK       # never fold for free, whatever it says
        if kind == RAISE and not view["can_raise"]:
            kind = CALL if view["to_call"] > 0 else CHECK
        amount = 0
        if kind == RAISE:
            amount = int(data.get("raise_to") or 0)
            amount = max(view["min_raise_to"], min(view["max_raise_to"], amount))
            if amount >= view["max_raise_to"]:
                kind, amount = ALL_IN, 0
        out = dict(base, action=kind, amount=amount, source="llm")
        line = _one_sentence(data.get("line"))
        if line:
            out["line"] = line
        reasoning = str(data.get("reasoning") or "").strip()
        if reasoning:
            out["reasoning"] = reasoning[:400]
        try:
            confidence = float(data.get("confidence"))
            out["confidence"] = round(max(0.05, min(0.99, confidence)), 2)
        except (TypeError, ValueError):
            pass
        # Graft the model's per-opponent reads onto our structured rows, so the
        # bars stay honest arithmetic and the words come from the coach.
        notes = {}
        for row in data.get("reads") or []:
            if isinstance(row, dict) and row.get("name"):
                notes[str(row["name"])] = str(row.get("note") or "")[:120]
        for read in out["reads"]:
            if notes.get(read["name"]):
                read["note"] = notes[read["name"]]
        return out

    def _ask_advice(self, view, odds_payload, base):
        messages = [
            {"role": "system", "content": ADVISE_SYSTEM.format(
                name=ADVISOR["name"], style=ADVISOR["style"]) + _lang_note(self.lang)},
            {"role": "user", "content": build_advice_prompt(view, odds_payload, base)},
        ]
        raw = self._create(messages, json_mode=True, effort="low")
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON in advice reply")
        return json.loads(match.group(0))

    def verdict(self, context):
        tone = verdict_tone(context)
        if self.client is None:
            return self.fallback.verdict(context)
        try:
            messages = [
                {"role": "system", "content": VERDICT_SYSTEM.format(
                    name=ADVISOR["name"], style=ADVISOR["style"]) + _lang_note(self.lang)},
                {"role": "user", "content": build_verdict_prompt(context, tone)},
            ]
            line = _one_sentence(self._create(messages, json_mode=False, effort="low"))
        except Exception:
            return self.fallback.verdict(context)
        if not line:
            return self.fallback.verdict(context)
        return tone, line

    def send_off(self, payload):
        """The written closing statement. A player who never played a hand gets
        the canned line — there is nothing to sum up."""
        if self.client is None or (payload.get("hands") or 0) <= 0:
            return self.fallback.send_off(payload)
        try:
            s = payload.get("session") or {}
            lines = [
                "The session is over. %s played %d hands and leaves at %+d chips."
                % (payload.get("name") or "Your player", payload["hands"], payload["net"]),
            ]
            if s.get("decisions"):
                lines.append("They followed %d of %d advised decisions; net %+d on hands "
                             "where they listened, %+d where they went their own way."
                             % (s["followed"], s["decisions"],
                                s["net_followed"], s["net_defied"]))
                leaks = ", ".join("%s ×%d" % (GRADE_WORDS[k], n)
                                  for k, n in (s.get("mistakes") or {}).items())
                if leaks:
                    lines.append("Recurring mistakes: %s." % leaks)
            lines.append("")
            lines.append("Walk them out. 2-4 spoken sentences.")
            messages = [
                {"role": "system", "content": SEND_OFF_SYSTEM.format(
                    name=ADVISOR["name"], style=ADVISOR["style"]) + _lang_note(self.lang)},
                {"role": "user", "content": "\n".join(lines)},
            ]
            raw = self._create(messages, json_mode=False, effort="low")
            text = " ".join(str(raw or "").split()).strip().strip('"')
        except Exception:
            return self.fallback.send_off(payload)
        return text[:400] or self.fallback.send_off(payload)

    def review(self, ctx):
        """The written debrief. Short hands (one advised decision, small pot)
        stay on canned lines — a model call per trivial fold is all cost and no
        insight; the engine flags which hands are worth real prose."""
        if self.client is None or not ctx.get("worth_prose"):
            return self.fallback.review(ctx)
        try:
            messages = [
                {"role": "system", "content": REVIEW_SYSTEM.format(
                    name=ADVISOR["name"], style=ADVISOR["style"]) + _lang_note(self.lang)},
                {"role": "user", "content": build_review_prompt(ctx)},
            ]
            raw = self._create(messages, json_mode=False, effort="low")
            text = " ".join(str(raw or "").split()).strip().strip('"')
        except Exception:
            return self.fallback.review(ctx)
        return text[:400] or self.fallback.review(ctx)

    def on_defiance(self, advice, action, view):
        if self.client is None:
            return self.fallback.on_defiance(advice, action, view)
        try:
            told = advice.get("action")
            if advice.get("action") == RAISE and advice.get("amount"):
                told = "raise to %d" % advice["amount"]
            did = action.kind
            if action.kind == RAISE and action.amount:
                did = "raise to %d" % action.amount
            messages = [
                {"role": "system", "content": DEFIANCE_SYSTEM.format(
                    name=ADVISOR["name"], style=ADVISOR["style"]) + _lang_note(self.lang)},
                {"role": "user", "content":
                    ("You said: %s. They did: %s.\nBoard: %s. Pot: %d.\nYour line was: \"%s\"\n\n"
                     "React in one sentence."
                     % (told, did, _board_text(view["board"]), view["pot"],
                        advice.get("line") or ""))},
            ]
            line = _one_sentence(self._create(messages, json_mode=False, effort="low"))
        except Exception:
            return self.fallback.on_defiance(advice, action, view)
        return line or self.fallback.on_defiance(advice, action, view)
