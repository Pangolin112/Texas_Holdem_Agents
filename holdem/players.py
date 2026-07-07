"""Players: the human at the keyboard and the LLM-driven seats."""

from . import ui
from .ui import QuitGame  # noqa: F401  (re-exported for convenience)

FOLD = "fold"
CHECK = "check"
CALL = "call"
RAISE = "raise"
ALL_IN = "all_in"


class Action:
    __slots__ = ("kind", "amount")

    def __init__(self, kind, amount=0):
        self.kind = kind
        self.amount = amount

    def __repr__(self):
        return "Action(%r, %r)" % (self.kind, self.amount)


class Player:
    is_human = False

    def __init__(self, name, stack):
        self.name = name
        self.stack = stack
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_street = 0  # chips put in on the current street
        self.committed = 0   # chips put in over the whole hand

    def reset_for_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_street = 0
        self.committed = 0

    @property
    def in_hand(self):
        return not self.folded

    def decide(self, view):
        """Return (Action, table_talk_or_None)."""
        raise NotImplementedError


class HumanPlayer(Player):
    is_human = True

    def decide(self, view):
        ui.show_table(view)
        pending_say = None
        while True:
            raw = ui.safe_input(" your move (h for help) > ").strip()
            low = raw.lower()

            if low in ("h", "help", "?"):
                ui.show_help()
                continue
            if low.startswith("say"):
                text = raw[3:].strip()
                if text:
                    pending_say = text[:100]
                    ui.out(ui.dim("   (you'll say that along with your action)"))
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
                    return Action(CHECK), pending_say
                return Action(FOLD), pending_say
            if low in ("", "c", "k", "check", "call"):
                if low == "" and view["to_call"] > 0:
                    ui.out(ui.dim("   facing a bet of %d — type c to call, f to fold"
                                  % view["to_call"]))
                    continue
                return Action(CALL if view["to_call"] > 0 else CHECK), pending_say
            if low in ("a", "all", "allin", "all-in"):
                return Action(ALL_IN), pending_say
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
                    return Action(ALL_IN), pending_say
                if amount < view["min_raise_to"]:
                    ui.out(ui.dim("   minimum raise is to %d (or 'a' for all-in)"
                                  % view["min_raise_to"]))
                    continue
                return Action(RAISE, amount), pending_say
            ui.out(ui.dim("   didn't catch that — h for help"))


class LLMPlayer(Player):
    is_human = False

    def __init__(self, name, stack, personality, brain):
        super().__init__(name, stack)
        self.personality = personality
        self.brain = brain

    def decide(self, view):
        return self.brain.decide(self, view)
