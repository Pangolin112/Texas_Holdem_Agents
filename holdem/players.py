"""Players: the human at the keyboard and the LLM-driven seats.

This module is the shared vocabulary between the game engine (which produces a
`PlayerView` each turn) and the brains (which consume it and return an
`Action`). The `Brain` protocol is the typed contract every seat's brain — LLM
or heuristic — satisfies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal, Optional, Protocol

from . import ui
from .ui import QuitGame  # noqa: F401  (re-exported for convenience)

if TYPE_CHECKING:
    from .cards import Card


ActionKind = Literal["fold", "check", "call", "raise", "all_in"]

# The read-only snapshot the engine hands a seat each time it must act. It's a
# plain dict (built in game.build_view); this alias just gives the signatures a
# readable name — no field-by-field TypedDict ceremony.
PlayerView = dict[str, Any]

FOLD: Final = "fold"
CHECK: Final = "check"
CALL: Final = "call"
RAISE: Final = "raise"
ALL_IN: Final = "all_in"


class Action:
    __slots__ = ("kind", "amount")

    def __init__(self, kind: ActionKind, amount: int = 0) -> None:
        self.kind = kind
        self.amount = amount

    def __repr__(self) -> str:
        return "Action(%r, %r)" % (self.kind, self.amount)


class Brain(Protocol):
    """The contract every seat's brain satisfies — heuristic or LLM. The engine
    only ever talks to a brain through these methods."""

    is_llm: bool

    def decide(self, player: "Player", view: PlayerView) -> tuple[Action, Optional[str]]:
        ...

    def buy_decision(self, player: "Player", cap: int, starting_stack: int,
                     table: Optional[dict] = None) -> int:
        ...

    def chat_reply(self, player: "Player", situation: str, chat: list[tuple[str, str]],
                   speaker_name: str, text: str,
                   addressed: Optional[str] = None) -> Optional[str]:
        ...

    def react(self, player: "Player", situation: str, chat: list[tuple[str, str]],
              event: str) -> Optional[str]:
        ...

    def explain_move(self, player: "Player", situation: str, chat: list[tuple[str, str]],
                     questioner: str, question: str) -> Optional[str]:
        ...


class Player:
    is_human: bool = False

    def __init__(self, name: str, stack: int) -> None:
        self.name = name
        self.stack = stack
        self.debt = 0             # chips borrowed from the house via rebuys
        self.hole: list[Card] = []
        self.folded = False
        self.all_in = False
        self.bet_street = 0       # chips put in on the current street
        self.committed = 0        # chips put in over the whole hand

    def reset_for_hand(self) -> None:
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_street = 0
        self.committed = 0

    @property
    def in_hand(self) -> bool:
        return not self.folded

    def decide(self, view: PlayerView) -> tuple[Action, Optional[str]]:
        """Return (Action, table_talk_or_None)."""
        raise NotImplementedError


class HumanPlayer(Player):
    is_human: bool = True

    def decide(self, view: PlayerView) -> tuple[Action, Optional[str]]:
        ui.show_table(view)
        while True:
            raw = ui.safe_input(" your move (h for help) > ").strip()
            low = raw.lower()

            if low in ("h", "help", "?"):
                ui.show_help()
                continue
            if low.startswith("say"):
                text = raw[3:].strip()
                if text:
                    view["broadcast"](text)  # heard immediately; the table answers
                else:
                    ui.out(ui.dim("   usage: say <something>"))
                continue
            if low in ("q", "quit", "exit"):
                sure = ui.safe_input(" leave the table for good? [y/N] ").strip().lower()
                if sure in ("y", "yes"):
                    raise QuitGame
                continue
            if low in ("f", "fold"):
                if view["to_call"] == 0:
                    ui.out(ui.dim("   (nothing to call — checking instead of folding)"))
                    return Action(CHECK), None
                return Action(FOLD), None
            if low in ("", "c", "k", "check", "call"):
                if low == "" and view["to_call"] > 0:
                    ui.out(ui.dim("   facing a bet of %d — type c to call, f to fold"
                                  % view["to_call"]))
                    continue
                return Action(CALL if view["to_call"] > 0 else CHECK), None
            if low in ("a", "all", "allin", "all-in"):
                return Action(ALL_IN), None
            if low.startswith("r") or low.startswith("bet"):
                rest = "".join(ch for ch in low if ch.isdigit())
                if not rest:
                    ui.out(ui.dim("   usage: r <amount>  (total for this street, e.g. r %d)"
                                  % view["min_raise_to"]))
                    continue
                amount = int(rest)
                if not view["can_raise"]:
                    ui.out(ui.dim("   you can't raise here — only call, fold or all-in"))
                    continue
                if amount >= view["max_raise_to"]:
                    return Action(ALL_IN), None
                if amount < view["min_raise_to"]:
                    ui.out(ui.dim("   minimum raise is to %d (or 'a' for all-in)"
                                  % view["min_raise_to"]))
                    continue
                return Action(RAISE, amount), None
            ui.out(ui.dim("   didn't catch that — h for help"))


class LLMPlayer(Player):
    is_human: bool = False

    def __init__(self, name: str, stack: int, personality: dict[str, Any],
                 brain: Brain) -> None:
        super().__init__(name, stack)
        self.personality = personality
        self.brain = brain

    def decide(self, view: PlayerView) -> tuple[Action, Optional[str]]:
        return self.brain.decide(self, view)
