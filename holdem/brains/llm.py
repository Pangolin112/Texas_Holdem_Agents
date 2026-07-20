"""LLM-backed decision-making: talk to the model, then keep it honest."""

from __future__ import annotations

import json
import random
import re
from typing import Any, Optional

from .. import ui
from ..players import Action, Brain, Player, PlayerView, FOLD, CHECK, CALL, RAISE, ALL_IN
from .heuristic import HeuristicBrain
from .model_chain import ModelChain, _is_model_error
from .personalities import _lang_note
from .prompts import (SYSTEM_TEMPLATE, CHAT_SYSTEM_TEMPLATE, EXPLAIN_SYSTEM_TEMPLATE,
                      BUY_SYSTEM_TEMPLATE, format_chat, build_user_prompt)
from .skill import skill_level
from .speech import reconcile_action


class ModelCaller:
    """Everything about *talking to the endpoint*, with none of the poker.

    The model chain, the automatic downgrade when an id isn't available, and
    the retry for endpoints that reject response_format/temperature live here so
    a seat's brain and the player's advisor (holdem/advisor.py) share one
    battle-tested path to the API instead of two drifting copies.
    """

    def __init__(self, client: Any, model: "str | ModelChain") -> None:
        self.client = client
        # `model` may be a plain id (tests, simple calls) or a shared ModelChain.
        self.chain = model if isinstance(model, ModelChain) else ModelChain([model])

    @property
    def model(self) -> str:
        return self.chain.current

    def _one_call(self, model, messages, json_mode, effort, plain=False):
        kwargs = {"model": model, "messages": messages}
        if not plain:
            # deepseek-reasoner (like the OpenAI o-series) rejects response_format,
            # temperature and other sampling params — send the bare request.
            ds_reasoner = model.startswith("deepseek-reasoner")
            if json_mode and not ds_reasoner:
                kwargs["response_format"] = {"type": "json_object"}
            if model.startswith(("gpt-5", "o1", "o3", "o4")):
                kwargs["reasoning_effort"] = effort
            elif not ds_reasoner:
                kwargs["temperature"] = 1.0
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def _create(self, messages, json_mode=True, effort="low"):
        # `effort` trades speed for depth: "low" for quick decisions and banter,
        # higher when the player asks a seat to justify its reasoning.
        last = None
        for _ in range(len(self.chain.models) + 1):
            model = self.chain.current
            try:
                return self._one_call(model, messages, json_mode, effort)
            except Exception as exc:
                last = exc
                if _is_model_error(exc):
                    if self.chain.downgrade():
                        ui.warn("model '%s' unavailable — switching to '%s'."
                                % (model, self.chain.current))
                        continue
                    raise
                # A response_format / temperature / reasoning quirk: retry once
                # as a plain call before giving up on this model.
                try:
                    return self._one_call(model, messages, json_mode, effort, plain=True)
                except Exception as exc2:
                    last = exc2
                    if _is_model_error(exc2) and self.chain.downgrade():
                        continue
                    raise
        raise last


class LLMBrain(ModelCaller, Brain):
    is_llm: bool = True

    def __init__(self, client: Any, model: "str | ModelChain",
                 personality: dict[str, Any], rng: random.Random,
                 lang: str = "en", skill: "str | dict" = "standard") -> None:
        super().__init__(client, model)
        self.p = personality
        self.lang = lang
        self.skill = skill_level(skill)
        self.fallback = HeuristicBrain(personality, rng, lang)
        self._warned = False

    def decide(self, player: Player, view: PlayerView) -> tuple[Action, Optional[str]]:
        if view.get("fast"):
            # The human has folded this hand: nobody left at the table is being
            # read or bluffed, so finish it on instinct — the same personality
            # weights, none of the per-move model latency. The player is
            # waiting on the next deal, not on this pot.
            return self.fallback.decide(player, view)
        ui.thinking(player.name)
        try:
            raw = self._ask(player, view)
            return self._parse(raw, view)
        except Exception as exc:  # any API/parse failure -> heuristic keeps game alive
            if not self._warned:
                ui.warn("%s's uplink glitched (%s: %s) — playing on instinct."
                        % (player.name, type(exc).__name__, str(exc)[:120]))
                self._warned = True
            return self.fallback.decide(player, view)

    def buy_decision(self, player: Player, cap: int, starting_stack: int,
                     table: Optional[dict] = None) -> int:
        """Let the agent genuinely decide, via the model, how many chips to buy
        before the next hand (0 to skip, at most `cap`). Only a seat below a
        full buy-in bothers to weigh it — a comfortably stacked one stands pat
        without spending a call. Any API/parse failure falls back to instinct."""
        if player.stack >= starting_stack:
            return 0
        try:
            return self._ask_buy(player, cap, starting_stack, table or {})
        except Exception:
            return self.fallback.buy_decision(player, cap, starting_stack, table)

    def _ask_buy(self, player, cap, starting_stack, table):
        sb, bb = table.get("blinds", (0, 0))
        standings = table.get("standings") or []
        stand_txt = "\n".join(
            "- %s: stack %d%s" % (n, s, (", owes the house %d" % d) if d else "")
            for n, s, d in standings) or "(just you at the table)"
        memory = table.get("memory") or []
        mem_txt = "\n".join(memory[-5:]) or "(this is the first hand)"
        messages = [
            {"role": "system", "content": BUY_SYSTEM_TEMPLATE.format(
                name=player.name, style=self.p["style"], cap=cap) + _lang_note(self.lang)},
            {"role": "user", "content":
                ("Your stack: %d. Your tab so far: %d. A full buy-in is %d. Blinds %d/%d.\n\n"
                 "How everyone stands right now (by net worth):\n%s\n\n"
                 "Recent hands this session:\n%s\n\n"
                 "How many chips do you buy before the next hand? 0 to skip, at most %d. "
                 "Respond with the JSON object only."
                 % (player.stack, player.debt, starting_stack, sb, bb,
                    stand_txt, mem_txt, cap))},
        ]
        raw = self._create(messages)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON in buy reply")
        amount = int(json.loads(match.group(0)).get("buy") or 0)
        return max(0, min(amount, cap))

    def _ask(self, player, view):
        messages = [
            {"role": "system",
             "content": SYSTEM_TEMPLATE.format(name=player.name, style=self.p["style"])
                        + self.skill["note"] + _lang_note(self.lang)},
            {"role": "user", "content": build_user_prompt(player, view, self.skill)},
        ]
        return self._create(messages, effort=self.skill["effort"])

    def _one_liner(self, player, body):
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_TEMPLATE.format(
                name=player.name, style=self.p["style"]) + _lang_note(self.lang)},
            {"role": "user", "content": body},
        ]
        raw = self._create(messages, json_mode=False).strip()
        line = raw.splitlines()[0].strip().strip('"').strip() if raw else ""
        if not line or line.upper() == "SILENT":
            return None
        return line[:140]

    def chat_reply(self, player: Player, situation: str, chat: list[tuple[str, str]],
                   speaker_name: str, text: str,
                   addressed: Optional[str] = None) -> Optional[str]:
        try:
            if addressed == "you":
                said = ('%s just spoke to YOU: "%s" — answer them.'
                        % (speaker_name, text))
            elif addressed:
                said = ('%s just said to %s: "%s" — you\'re only overhearing this; '
                        'chime in only if you have something worth adding.'
                        % (speaker_name, addressed, text))
            else:
                said = '%s just said to the table: "%s"' % (speaker_name, text)
            return self._one_liner(player,
                                   "%s\n\nRecent table talk:\n%s\n\n%s\n"
                                   "Your reply (one short line, or SILENT):"
                                   % (situation, format_chat(chat), said))
        except Exception:
            return self.fallback.chat_reply(player, situation, chat,
                                            speaker_name, text, addressed)

    def react(self, player: Player, situation: str, chat: list[tuple[str, str]],
              event: str) -> Optional[str]:
        try:
            return self._one_liner(player,
                                   "%s\n\nRecent table talk:\n%s\n\nWhat just happened: %s\n"
                                   "If that's worth a remark, say one short line (name whoever "
                                   "it concerns if natural); otherwise reply exactly SILENT:"
                                   % (situation, format_chat(chat), event))
        except Exception:
            return self.fallback.react(player, situation, chat, event)

    def explain_move(self, player: Player, situation: str, chat: list[tuple[str, str]],
                     questioner: str, question: str) -> Optional[str]:
        """The player questioned this seat's play. After the hand: the real
        reasoning, step by step. Mid-hand: the seat guards its strategy — it
        may deflect or sell a story. Kept at "low" reasoning effort: the
        prompt already asks for the genuine step-by-step logic, and low effort
        answers fast enough that the human isn't left waiting — a laggy reply
        kills the back-and-forth even when the content is good."""
        ui.thinking(player.name)  # show feedback while the model composes
        try:
            body = ("%s is questioning your play: \"%s\"\n\n"
                    "The situation and the action this hand:\n%s\n\n"
                    "Recent table talk:\n%s\n\n"
                    "Answer %s directly. If the hand is over, walk them through your actual "
                    "thinking on that decision, step by step: your read on the board, how "
                    "strong you were, the pot odds and the price you were getting, your "
                    "position, the stack sizes, what you were trying to represent, and what "
                    "you expected them to do — concrete, with the real cards and amounts. "
                    "If the hand is still live, protect your game: deflect, give away as "
                    "little as you like, or sell them the story you want believed — just "
                    "stay coherent with how you've played. A few plain sentences either way."
                    % (questioner, question, situation, format_chat(chat), questioner))
            messages = [
                {"role": "system", "content": EXPLAIN_SYSTEM_TEMPLATE.format(
                    name=player.name, style=self.p["style"]) + _lang_note(self.lang)},
                {"role": "user", "content": body},
            ]
            raw = self._create(messages, json_mode=False, effort="low").strip()
            text = " ".join(raw.split())  # fold any line breaks into one spoken turn
            if not text or text.upper() == "SILENT":
                return None
            return text[:500]
        except Exception:
            return self.fallback.explain_move(player, situation, chat, questioner, question)

    def _parse(self, raw, view):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON in model reply")
        data = json.loads(match.group(0))

        say = str(data.get("say") or "").strip()[:100] or None
        action = self._mechanical_action(data, view)
        # A player may bluff about their cards, but their spoken move must match
        # what they actually do — reconcile any mismatch in favor of the words.
        return reconcile_action(action, say, view, data.get("raise_to"))

    @staticmethod
    def _mechanical_action(data, view):
        kind = str(data.get("action", "")).strip().lower().replace("-", "_").replace(" ", "_")
        if kind == "bet":
            kind = RAISE
        if kind == FOLD:
            # Folding when checking is free is never right; take the free card.
            return Action(CHECK) if view["to_call"] == 0 else Action(FOLD)
        if kind in (CHECK, CALL):
            return Action(CHECK) if view["to_call"] == 0 else Action(CALL)
        if kind == ALL_IN:
            return Action(ALL_IN)
        if kind == RAISE:
            if not view["can_raise"]:
                return Action(CALL)
            try:
                target = int(data.get("raise_to") or 0)
            except (TypeError, ValueError):
                target = view["min_raise_to"]
            target = max(view["min_raise_to"], min(target, view["max_raise_to"]))
            return Action(RAISE, target)
        raise ValueError("unknown action %r" % kind)
