"""The scored-action policy machinery shared by every offline-capable seat."""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from typing import Any, Optional

from ..cards import Card
from ..players import (Action, ActionKind, Brain, Player, PlayerView,
                       FOLD, CHECK, CALL, RAISE, ALL_IN)


def _softmax(scores: list[float], temp: float) -> list[float]:
    """Boltzmann distribution over action utilities. `temp` is the player's
    unpredictability: low temp -> near-deterministic (almost always the top
    action), high temp -> loose and mixed. Returns probabilities aligned with
    `scores`. Kept in pure Python — this is a handful of actions on the hot
    decision path; vectorise (numpy) only if/when the weights become learned."""
    t = max(temp, 0.05)
    m = max(scores)
    exps = [math.exp((s - m) / t) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


# ---------------------------------------------------------------------------
# Policy brains: an abstract scored-action base, and the heuristic seat that
# implements it (also powers --offline mode and the LLM fallback).
# ---------------------------------------------------------------------------

class PolicyBrain(Brain, ABC):
    """Shared machinery for a seat that plays by a scored-action policy.

    It decides by scoring each legal action, dropping the ones that are clearly
    dominated, and sampling the rest from a Boltzmann distribution whose
    temperature is the seat's unpredictability — then sizing any raise. It also
    carries the table presence (taunts, chat, reactions, buy-ins) common to these
    characters. Subclasses supply the two things that actually differ between
    characters:

        _strength(hole, board)          -> how good the hand looks, in [0, 1]
        _action_utilities(player, view, strength) -> how the personality weighs
                                                     each legal move

    Everything else — sampling, dominated-move pruning, bet sizing, table talk —
    is inherited, so a future learned-weights seat overrides `_action_utilities`
    (and maybe `_strength`) and nothing else."""

    is_llm: bool = False

    # An action this much worse (in utility) than the best available is treated
    # as a no-brainer to skip, not a rare mixed line. Tune with `_action_utilities`.
    DOMINATED_BAND: float = 0.85

    def __init__(self, personality: dict[str, Any], rng: random.Random,
                 lang: str = "en") -> None:
        self.p = personality
        self.rng = rng
        self.lang = lang
        self._last_choice: list[tuple[ActionKind, float]] = []

    # -- extension points (subclasses MUST implement) -----------------------

    @abstractmethod
    def _strength(self, hole: list[Card], board: list[Card]) -> float:
        """How strong the hand looks right now, in [0, 1]."""
        ...

    @abstractmethod
    def _action_utilities(self, player: Player, view: PlayerView,
                          strength: float) -> list[tuple[ActionKind, float]]:
        """Return a list of (action_kind, utility) over the *legal* actions.
        This is where personality lives — as weights on hand strength, pot odds
        and bluff appetite, not as scattered thresholds. `decide` turns the
        utilities into a Boltzmann distribution and samples one."""
        ...

    # -- table talk ---------------------------------------------------------

    def _taunts(self) -> list[str]:
        if self.lang == "zh" and self.p.get("taunts_zh"):
            return self.p["taunts_zh"]
        return self.p["taunts"]

    # -- decision -----------------------------------------------------------

    # How unpredictable this seat is: the softmax temperature. Low -> the player
    # almost always takes the highest-utility line; high -> loose and mixed.
    # Looser, more aggressive personalities mix more. An explicit
    # `unpredictability` on the personality overrides the derived default —
    # that's the seam for adding it as a first-class character axis later.
    def _temperature(self) -> float:
        if "unpredictability" in self.p:
            return self.p["unpredictability"]
        loose = self.p["looseness"]
        aggr = self.p["aggression"]
        return 0.30 + loose * 0.30 + (aggr - 0.5) * 0.12

    def decide(self, player: Player, view: PlayerView) -> tuple[Action, Optional[str]]:
        strength = self._strength(player.hole, view["board"])
        rng = self.rng
        say = rng.choice(self._taunts()) if rng.random() < 0.18 else None

        # 1. score legal actions  2. soften into a distribution  3. sample.
        utils = self._action_utilities(player, view, strength)
        # A person won't take a line that's clearly far worse than their best
        # option; without this the softmax tail leaks probability onto dominated
        # actions (e.g. folding the nuts to a shove). Drop the no-brainer-bad ones.
        best = max(u for _, u in utils)
        utils = [(k, u) for k, u in utils if u >= best - self.DOMINATED_BAND]
        kinds = [k for k, _ in utils]
        probs = _softmax([u for _, u in utils], self._temperature())
        # Kept for explain_move / debugging: what the seat weighed this time.
        self._last_choice = list(zip(kinds, probs))

        r = rng.random()
        cum = 0.0
        kind = kinds[-1]
        for k, prob in zip(kinds, probs):
            cum += prob
            if r <= cum:
                kind = k
                break

        if kind == FOLD:
            return Action(FOLD), None  # fold quietly, no trash talk
        if kind == CHECK:
            return Action(CHECK), say
        if kind == CALL:
            return Action(CALL), say
        if kind == ALL_IN:
            return Action(ALL_IN), say

        # RAISE: sizing is unchanged from before — a pot-proportional target,
        # clamped to the legal window.
        pot = max(view["pot"], 1)
        to_call = view["to_call"]
        min_to = view["min_raise_to"]
        max_to = view["max_raise_to"]
        bb = view["blinds"][1]
        if to_call == 0:
            target = int(pot * (0.5 + rng.random() * 0.7))
            target = max(min_to, min(max(target, bb), max_to))
        else:
            target = int((pot + to_call) * (0.8 + rng.random() * 0.7))
            target = max(min_to, min(target, max_to))
        return Action(RAISE, target), say

    def buy_decision(self, player: Player, cap: int, starting_stack: int,
                     table: Optional[dict] = None) -> int:
        """Voluntary top-up before the next hand. Returns chips to buy (0 =
        stand pat), never more than `cap`. Only a short stack gets reloaded,
        and looser/bolder players reload sooner and closer to a full stack.
        (`table` is ignored here — the offline brain goes on instinct.)"""
        stack = player.stack
        if stack >= 0.6 * starting_stack:
            return 0  # still deep enough to play — no need to reload
        loose = self.p["looseness"]
        aggr = self.p["aggression"]
        shortness = 1.0 - stack / float(starting_stack)  # ~0 full .. ~1 near broke
        chance = 0.10 + shortness * 0.55 + (loose - 0.5) * 0.30 + (aggr - 0.5) * 0.20
        if self.rng.random() >= chance:
            return 0
        want = starting_stack - stack  # reload back toward a full stack
        return max(0, min(want, cap))

    def chat_reply(self, player: Player, situation: str, chat: list[tuple[str, str]],
                   speaker_name: str, text: str,
                   addressed: Optional[str] = None) -> Optional[str]:
        # Spoken to directly -> almost always answer; general remark -> often;
        # overhearing someone else's exchange -> rarely butt in.
        chance = 0.95 if addressed == "you" else (0.2 if addressed else 0.6)
        if self.rng.random() < chance:
            return self.rng.choice(self._taunts())
        return None

    def react(self, player: Player, situation: str, chat: list[tuple[str, str]],
              event: str) -> Optional[str]:
        if self.rng.random() < 0.7:
            return self.rng.choice(self._taunts())
        return None

    def explain_move(self, player: Player, situation: str, chat: list[tuple[str, str]],
                     questioner: str, question: str) -> str:
        # No live reasoning model offline, but still give a grounded, coherent
        # answer rather than a throwaway line.
        if self.lang == "zh":
            style = "打得凶" if self.p["aggression"] > 0.6 else "打得稳"
            loose = ("什么牌我都愿意赌一把" if self.p["looseness"] > 0.6
                     else "我只玩自己看得上的牌")
            return (("问得好，%s。" % questioner)
                    + "我看了看牌面和底池的大小，掂量了一下自己的牌力值不值这个价，"
                      "也想了想你们之前是怎么下注的。"
                    + ("我这人%s，而且%s，所以按位置和筹码来说，这就是我最舒服的"
                       "打法——不是瞎来的。" % (style, loose)))
        style = ("aggressive" if self.p["aggression"] > 0.6 else "careful")
        loose = ("I'll gamble with a lot of hands" if self.p["looseness"] > 0.6
                 else "I only get involved with hands I like")
        return (("Fair question, %s. " % questioner)
                + ("I looked at the board and the size of the pot, weighed how strong I "
                   "really was against the price I was being asked to pay, and thought about "
                   "how you'd been betting. ")
                + ("I play %s and %s, so given my position and the stacks it was the line I "
                   "was comfortable with — not a random punt." % (style, loose)))


def preflop_strength(hole: list[Card]) -> float:
    """How good two cards look before any board, in [0, 1].

    A cheap stand-in for real preflop equity: pairs, high cards, suitedness and
    connectedness. Shared with holdem/ranges.py, which needs to score a
    thousand candidate holdings per opponent and can't afford to simulate each.
    """
    a, b = sorted((c.value for c in hole), reverse=True)
    if a == b:
        return 0.50 + (a - 2) / 24.0  # 22 ≈ 0.50 ... AA = 1.0
    s = (a + b) / 27.0 * 0.42
    if hole[0].suit == hole[1].suit:
        s += 0.07
    gap = a - b
    if gap == 1:
        s += 0.06
    elif gap == 2:
        s += 0.03
    if a >= 11 and b >= 11:
        s += 0.12
    elif a == 14:
        s += 0.05
    return min(s, 0.95)
