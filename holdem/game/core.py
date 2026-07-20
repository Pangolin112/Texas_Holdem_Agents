"""The game's spine: setup, the outer hand loop, and the small bits of state
every mixin shares (`self.players`, `self.hand_players`, the pot, and so on)."""

from __future__ import annotations

import random
import threading

from .. import ui
from .buyins import BuyInsMixin
from .chat import ChatMixin, looks_like_move_question  # noqa: F401  (re-exported)
from .coach import CoachMixin
from .hand_flow import HandFlowMixin


class TexasHoldemGame(ChatMixin, BuyInsMixin, HandFlowMixin, CoachMixin):
    def __init__(self, players, sb=10, bb=20, rng=None, interactive=True,
                 reveal_all=False, language="en", show_odds=True, advisor=None,
                 fast_forward=True):
        self.players = list(players)  # seat order; only players with chips
        self.sb = sb
        self.bb = bb
        self.rng = rng if rng is not None else random.SystemRandom()
        self.interactive = interactive
        self.reveal_all = reveal_all  # peek mode: show every hand once it's over
        self.language = language      # what the agents speak ("en" / "zh")
        self.show_odds = show_odds    # live equity read for the human seat
        # Once the human folds, the rest of the hand is bots settling a pot the
        # player has no stake in — hurry it (instinct decisions, no commentary)
        # so the next deal comes fast. See hero_out().
        self.fast_forward = fast_forward
        # The coach behind the player's chair (holdem/advisor.py), or None for
        # nobody. It needs the equity numbers, so it can't work without them.
        self.advisor = advisor if show_odds else None
        # The coach's ledger on the player, across the whole session — this is
        # what lets the debrief talk about habits instead of moments. Never
        # reset between hands; that's the point of it.
        self.coach_session = {"hands": 0, "decisions": 0, "followed": 0,
                              "net": 0, "net_followed": 0, "net_defied": 0,
                              "mistakes": {}}
        self.starting_stack = players[0].stack if players else 0
        self.button_idx = 0
        self.hand_no = 0
        self.memory = []  # one-line summaries of past hands, fed to the AIs
        # The public book on every seat: session-long counters of what each
        # player has visibly done (hands played, raises, calls, showdowns).
        # Built only from public moves and shown cards, and handed to every
        # brain — the seats AND the coach read the same experience.
        self.style_stats = {}
        self._hand_vpip = set()   # names that voluntarily put chips in preflop
        self._hand_pfr = set()    # names that raised preflop
        self._hand_aggr = set()   # names that bet/raised at any point this hand
        # The coach runs in the background so the player never waits on it:
        # this lock guards the advice log, the current task and publication.
        self.advice_lock = threading.Lock()
        self._advice_task = None
        # Serializes all chat delivery. Re-entrant because a reply is delivered
        # from inside delivering the line it answers. A front-end may call
        # table_talk() from another thread (the web app lets the human speak at
        # ANY time, even while a seat is mid-decision) — the lock keeps the
        # chat log and the one-reply rule consistent across threads.
        self.talk_lock = threading.RLock()

        # per-hand state
        self.board = []
        self.hand_players = []
        self.current_bet = 0
        self.min_raise = bb
        self.street = "PREFLOP"
        self.history = []  # list of (street, text)
        self.chat = []     # list of (name, text)
        self.revealed = False
        self.hand_live = False
        self.shown = set()          # names whose hole cards went public this hand
        self.hand_winnings = {}     # name -> chips collected this hand
        self.hand_actions = []      # structured moves this hand (the coach's evidence)
        self.hero_advice = None     # the coach's call on the spot in front of us
        self.advice_log = []        # every call it made this hand, and what we did
        self.hero_odds_payload = None
        self._odds_cache = {}       # (hole, board, live opponents) -> odds payload
        self._odds_shown = None     # last key handed to the front-end

    # ------------------------------------------------------------------ util

    @property
    def human(self):
        for p in self.players:
            if p.is_human:
                return p
        return None

    def record(self, player, text):
        self.history.append((self.street, "%s %s" % (player.name, text)))

    def commit(self, player, amount):
        amount = min(amount, player.stack)
        player.stack -= amount
        player.bet_street += amount
        player.committed += amount
        if player.stack == 0:
            player.all_in = True
        return amount

    def pot_total(self):
        return sum(p.committed for p in self.hand_players)

    def player_by_name(self, name):
        for p in self.players:
            if p.name == name:
                return p
        return None

    # -------------------------------------------------- the book on everyone

    def _style(self, name):
        return self.style_stats.setdefault(name, {
            "hands": 0, "vpip": 0, "pfr": 0, "raises": 0, "calls": 0,
            "folds": 0, "allins": 0, "showdowns": []})

    def note_style(self, p, kind):
        """Book one public move into the session ledger on this seat. Only
        ever fed by moves everyone at the table saw."""
        s = self._style(p.name)
        if kind == "fold":
            s["folds"] += 1
        elif kind == "call":
            s["calls"] += 1
            if self.street == "PREFLOP":
                self._hand_vpip.add(p.name)
        elif kind in ("bet", "raise", "all_in"):
            s["raises"] += 1
            self._hand_aggr.add(p.name)
            if kind == "all_in":
                s["allins"] += 1
            if self.street == "PREFLOP":
                self._hand_vpip.add(p.name)
                self._hand_pfr.add(p.name)

    def style_profiles(self, viewer):
        """The book on every player except `viewer`, for a brain's prompt.
        Nothing here that a person at the table couldn't remember: counts of
        public moves, and cards that were actually shown."""
        rows = []
        for pl in self.players:
            if pl is viewer:
                continue
            s = self.style_stats.get(pl.name)
            if not s or s["hands"] < 2:
                continue  # one hand of anything reads as nothing
            rows.append(dict(s, name=pl.name, showdowns=list(s["showdowns"])))
        return rows

    def hero_out(self):
        """True while the human has folded out of a live hand — the stretch
        where nobody at the table is being read, bluffed, or entertained.

        Deliberately NOT true when the human is all-in: an all-in player still
        has the pot at stake, and whether the others fold or fight decides how
        much of it they win — those moves deserve real thought. A folded player
        has nothing riding on anything; speed is worth more than drama.
        """
        human = self.human
        return (self.fast_forward and self.hand_live
                and human is not None and human.folded)

    # ------------------------------------------------------------- main loop

    def run(self, max_hands=None):
        if len(self.players) < 2:
            return
        while True:
            self.play_hand()
            self.handle_rebuys()
            if max_hands is not None and self.hand_no >= max_hands:
                break
            if self.interactive and not self.between_hands():
                break
            self.button_idx = (self.button_idx + 1) % len(self.players)
        ui.show_standings(self.players, "final standings")

    def between_hands(self):
        """Top-ups, standings and chat between hands. Returns False to end."""
        self.ai_buy_ins()
        ui.show_standings(self.players)
        cap = self.starting_stack
        bought = 0  # the human may top up at most one starting stack per break
        while True:
            left = cap - bought
            buy_hint = ("buy <n> top up (up to %d) · " % left) if left > 0 else ""
            answer = ui.safe_input(
                "\n [Enter] next hand · %ssay <text> · q to quit > " % buy_hint).strip()
            low = answer.lower()
            if low in ("q", "quit", "exit"):
                return False
            if low.startswith("buy"):
                bought += self.human_buy(answer[3:].strip(), left)
                continue
            if low.startswith("say"):
                text = answer[3:].strip()
                if text:
                    self.table_talk(self.human, text)
                else:
                    ui.out(ui.dim("   usage: say <something>"))
                continue
            return True
