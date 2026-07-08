"""Rendering for the game.

By default every function here writes to the terminal, exactly as before. But
the engine only ever talks to the outside world through this module, so a
different front-end (the web app, a future 3D client) can take over by
installing a *sink* for the current thread with `set_sink`. When a sink is
active, each event function forwards its structured arguments to the sink
instead of printing, and `safe_input` reads the player's command from the sink.
This keeps a single shared game engine driving every version — terminal, web,
or 3D — with no duplicated game logic.
"""

import os
import threading

from .cards import RED_SUITS
from . import evaluator

QUIET = False  # silences all output (used by the test suite)

WIDTH = 58


class QuitGame(Exception):
    """Raised when the human wants to leave the table."""


# --------------------------------------------------------------------------- #
# Pluggable presentation sink
#
# The terminal is the default (no sink). A non-terminal front-end installs a
# Sink subclass on its engine thread; the methods below mirror the event
# functions in this module one-for-one. Defaults are no-ops so a sink only has
# to override what it cares about. `input` and `human_action` feed player input
# back into the engine.
# --------------------------------------------------------------------------- #

class Sink:
    def out(self, text):
        pass

    def input(self, prompt):
        raise QuitGame

    def title_screen(self):
        pass

    def hand_banner(self, hand_no, sb, bb, dealer_name):
        pass

    def street_banner(self, street, board, pot):
        pass

    def chat_line(self, name, text, to):
        pass

    def announce_action(self, player, desc):
        pass

    def thinking(self, name):
        pass

    def warn(self, text):
        pass

    def show_table(self, view):
        pass

    def show_help(self):
        pass

    def reveal_hands(self, players):
        pass

    def show_showdown(self, contenders, results, already_revealed):
        pass

    def reveal_all_hands(self, players, board):
        pass

    def announce_pot(self, text):
        pass

    def announce_buy(self, player, amount, debt):
        pass

    def announce_rebuy(self, player, stake, debt, line):
        pass

    def show_standings(self, players, title):
        pass


_local = threading.local()


def set_sink(sink):
    """Route this thread's game output/input through `sink` (None = terminal)."""
    _local.sink = sink


def get_sink():
    return getattr(_local, "sink", None)


def enable_colors():
    # Nudges legacy Windows consoles into processing ANSI escapes.
    if os.name == "nt":
        os.system("")


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"


def _c(code, text):
    return "%s%s%s" % (code, text, C.RESET)


def bold(t):
    return _c(C.BOLD, t)


def dim(t):
    return _c(C.DIM, t)


def out(text=""):
    sink = get_sink()
    if sink is not None:
        sink.out(text)
        return
    if not QUIET:
        print(text)


def safe_input(prompt):
    sink = get_sink()
    if sink is not None:
        return sink.input(prompt)
    if QUIET:
        raise QuitGame
    try:
        # A BOM can sneak in when input is piped from PowerShell.
        return input(prompt).lstrip("\ufeff")
    except EOFError:
        raise QuitGame from None


def card_str(card):
    s = str(card)
    if card.suit in RED_SUITS:
        return _c(C.RED, s)
    return _c(C.BOLD, s)


def cards_str(cards):
    return " ".join(card_str(c) for c in cards)


def name_str(player):
    return _c(C.GREEN if player.is_human else C.CYAN, player.name)


def title_screen():
    sink = get_sink()
    if sink is not None:
        sink.title_screen()
        return
    out()
    out(_c(C.YELLOW, "  ♠ ♥ ♦ ♣   N O - L I M I T   T E X A S   H O L D ' E M   ♣ ♦ ♥ ♠"))
    out(dim("                     you  vs.  the machines"))
    out()


def hand_banner(hand_no, sb, bb, dealer_name):
    sink = get_sink()
    if sink is not None:
        sink.hand_banner(hand_no, sb, bb, dealer_name)
        return
    out()
    out(_c(C.YELLOW, "═" * WIDTH))
    out(_c(C.YELLOW, " HAND #%d   ·   blinds %d/%d   ·   dealer: %s" % (hand_no, sb, bb, dealer_name)))
    out(_c(C.YELLOW, "═" * WIDTH))


def street_banner(street, board, pot):
    sink = get_sink()
    if sink is not None:
        sink.street_banner(street, board, pot)
        return
    out()
    board_txt = cards_str(board) if board else dim("(none)")
    out(" %s   board: %s   %s" % (bold("── " + street + " ──"), board_txt, _c(C.YELLOW, "pot %d" % pot)))


def chat_line(name, text, to=None):
    sink = get_sink()
    if sink is not None:
        sink.chat_line(name, text, to)
        return
    if to:
        out(_c(C.MAGENTA, '      %s (to %s): "%s"' % (name, to, text)))
    else:
        out(_c(C.MAGENTA, '      %s: "%s"' % (name, text)))


def announce_action(player, desc):
    sink = get_sink()
    if sink is not None:
        sink.announce_action(player, desc)
        return
    out("   %s %s." % (name_str(player), desc))


def thinking(name):
    sink = get_sink()
    if sink is not None:
        sink.thinking(name)
        return
    out(dim("   … %s is thinking" % name))


def warn(text):
    sink = get_sink()
    if sink is not None:
        sink.warn(text)
        return
    out(_c(C.RED, "   (!) " + text))


def show_table(view):
    sink = get_sink()
    if sink is not None:
        sink.show_table(view)
        return
    hero = view["hero"]
    out()
    out(dim("─" * WIDTH))
    board_txt = cards_str(view["board"]) if view["board"] else dim("(none)")
    out(" %s   board: %s   %s" % (bold(view["street"]), board_txt, _c(C.YELLOW, "pot %d" % view["pot"])))
    out(dim("─" * WIDTH))
    for pl in view["players"]:
        marker = _c(C.GREEN, "►") if pl["is_hero"] else " "
        button = "D" if pl["is_button"] else " "
        if pl["folded"]:
            status = dim("folded")
        elif pl["all_in"]:
            status = _c(C.RED, "ALL-IN")
        elif pl["bet_street"] > 0:
            status = "bet %d" % pl["bet_street"]
        else:
            status = ""
        color = C.GREEN if pl["is_hero"] else C.CYAN
        out(" %s %s %s %s  %s" % (marker, button, _c(color, pl["name"].ljust(14)),
                                  ("$%d" % pl["stack"]).rjust(7), status))
    out(dim("─" * WIDTH))
    hint = (" — you have " + bold(view["hero_hand_hint"])) if view.get("hero_hand_hint") else ""
    out(" your cards: %s%s" % (cards_str(hero["hole"]), hint))
    if view["to_call"] > 0:
        line = " to call: %s" % _c(C.YELLOW, str(view["to_call"]))
    else:
        line = " nothing to call — you may check"
    if view["can_raise"]:
        line += "  ·  raise-to range: %d–%d" % (view["min_raise_to"], view["max_raise_to"])
    out(line + "  ·  your stack: %d" % hero["stack"])


def show_help():
    sink = get_sink()
    if sink is not None:
        sink.show_help()
        return
    out(dim("   f            fold"))
    out(dim("   c            check (if free) / call"))
    out(dim("   r <amount>   raise TO <amount> total this street, e.g. 'r 120'"))
    out(dim("   a            all-in"))
    out(dim("   say <text>   chat with the table — they hear you and answer"))
    out(dim("   q            leave the table"))


def reveal_hands(players):
    sink = get_sink()
    if sink is not None:
        sink.reveal_hands(players)
        return
    out()
    out(bold(" ── all-in! hands on the table ──"))
    for p in players:
        out("   %s  %s" % (name_str(p).ljust(24), cards_str(p.hole)))


def show_showdown(contenders, results, already_revealed):
    sink = get_sink()
    if sink is not None:
        sink.show_showdown(contenders, results, already_revealed)
        return
    out()
    out(bold(" ── SHOWDOWN ──"))
    for p in contenders:
        rank, _best5 = results[p]
        out("   %s  %s  %s" % (name_str(p).ljust(24), cards_str(p.hole),
                               evaluator.hand_name(rank)))


def reveal_all_hands(players, board=None):
    """Peek mode: after the hand, lay every dealt seat's hole cards face up —
    folders included — so you can see what everyone was actually holding."""
    sink = get_sink()
    if sink is not None:
        sink.reveal_all_hands(players, board)
        return
    dealt = [p for p in players if p.hole]
    if not dealt:
        return
    out()
    out(bold(" ── everyone's cards (peek) ──"))
    for p in dealt:
        status = dim(" folded") if p.folded else ""
        hand_txt = ""
        if board is not None and len(p.hole) + len(board) >= 5:
            rank, _ = evaluator.best_hand(list(p.hole) + list(board))
            hand_txt = "  " + evaluator.hand_name(rank)
        out("   %s  %s%s%s" % (name_str(p).ljust(24), cards_str(p.hole),
                               status, hand_txt))


def announce_pot(text):
    sink = get_sink()
    if sink is not None:
        sink.announce_pot(text)
        return
    out(_c(C.YELLOW, "   ● " + text))


def announce_buy(player, amount, debt):
    sink = get_sink()
    if sink is not None:
        sink.announce_buy(player, amount, debt)
        return
    out(_c(C.YELLOW, "   $ %s buys in for %d more chips (tab now %d)."
           % (player.name, amount, debt)))


def announce_rebuy(player, stake, debt, line=None):
    sink = get_sink()
    if sink is not None:
        sink.announce_rebuy(player, stake, debt, line)
        return
    out()
    out(_c(C.YELLOW, " $ %s is felted — the house stakes another %d (tab now %d)."
           % (player.name, stake, debt)))
    if line:
        chat_line(player.name, line)


def show_standings(players, title="standings"):
    sink = get_sink()
    if sink is not None:
        sink.show_standings(players, title)
        return
    out()
    out(dim(" %s:" % title))
    for p in sorted(players, key=lambda x: -(x.stack - x.debt)):
        debt_txt = ""
        if p.debt:
            debt_txt = dim("   debt %d · net %+d" % (p.debt, p.stack - p.debt))
        out("   %s %s%s" % (name_str(p).ljust(24), ("$%d" % p.stack).rjust(7), debt_txt))
