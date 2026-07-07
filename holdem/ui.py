"""Terminal rendering for the game."""

import os

from .cards import RED_SUITS
from . import evaluator

QUIET = False  # silences all output (used by the test suite)

WIDTH = 58


class QuitGame(Exception):
    """Raised when the human wants to leave the table."""


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
    if not QUIET:
        print(text)


def safe_input(prompt):
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
    out()
    out(_c(C.YELLOW, "  ♠ ♥ ♦ ♣   N O - L I M I T   T E X A S   H O L D ' E M   ♣ ♦ ♥ ♠"))
    out(dim("                     you  vs.  the machines"))
    out()


def hand_banner(hand_no, sb, bb, dealer_name):
    out()
    out(_c(C.YELLOW, "═" * WIDTH))
    out(_c(C.YELLOW, " HAND #%d   ·   blinds %d/%d   ·   dealer: %s" % (hand_no, sb, bb, dealer_name)))
    out(_c(C.YELLOW, "═" * WIDTH))


def street_banner(street, board, pot):
    out()
    board_txt = cards_str(board) if board else dim("(none)")
    out(" %s   board: %s   %s" % (bold("── " + street + " ──"), board_txt, _c(C.YELLOW, "pot %d" % pot)))


def chat_line(name, text):
    out(_c(C.MAGENTA, '      %s: "%s"' % (name, text)))


def announce_action(player, desc, say=None):
    out("   %s %s." % (name_str(player), desc))
    if say:
        chat_line(player.name, say)


def thinking(name):
    out(dim("   … %s is thinking" % name))


def warn(text):
    out(_c(C.RED, "   (!) " + text))


def show_table(view):
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
    out(dim("   f            fold"))
    out(dim("   c            check (if free) / call"))
    out(dim("   r <amount>   raise TO <amount> total this street, e.g. 'r 120'"))
    out(dim("   a            all-in"))
    out(dim("   say <text>   chat with the table — they hear you and answer"))
    out(dim("   q            leave the table"))


def reveal_hands(players):
    out()
    out(bold(" ── all-in! hands on the table ──"))
    for p in players:
        out("   %s  %s" % (name_str(p).ljust(24), cards_str(p.hole)))


def show_showdown(contenders, results, already_revealed):
    out()
    out(bold(" ── SHOWDOWN ──"))
    for p in contenders:
        rank, _best5 = results[p]
        out("   %s  %s  %s" % (name_str(p).ljust(24), cards_str(p.hole),
                               evaluator.hand_name(rank)))


def announce_pot(text):
    out(_c(C.YELLOW, "   ● " + text))


def announce_rebuy(player, stake, debt, line=None):
    out()
    out(_c(C.YELLOW, " $ %s is felted — the house stakes another %d (tab now %d)."
           % (player.name, stake, debt)))
    if line:
        chat_line(player.name, line)


def show_standings(players, title="standings"):
    out()
    out(dim(" %s:" % title))
    for p in sorted(players, key=lambda x: -(x.stack - x.debt)):
        debt_txt = ""
        if p.debt:
            debt_txt = dim("   debt %d · net %+d" % (p.debt, p.stack - p.debt))
        out("   %s %s%s" % (name_str(p).ljust(24), ("$%d" % p.stack).rjust(7), debt_txt))
