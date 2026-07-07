"""No-Limit Texas Hold'em engine."""

import random
import time

from . import evaluator, ui
from .cards import Deck
from .players import Action, ALL_IN, CALL, CHECK, FOLD, RAISE


class TexasHoldemGame:
    def __init__(self, players, sb=10, bb=20, rng=None, fast=False, interactive=True):
        self.players = list(players)  # seat order; only players with chips
        self.sb = sb
        self.bb = bb
        self.rng = rng if rng is not None else random.SystemRandom()
        self.fast = fast
        self.interactive = interactive
        self.starting_stack = players[0].stack if players else 0
        self.button_idx = 0
        self.hand_no = 0
        self.memory = []  # one-line summaries of past hands, fed to the AIs

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

    # ------------------------------------------------------------------ util

    def pause(self, seconds=0.8):
        if not self.fast:
            time.sleep(seconds)

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
        """Standings and chat between hands. Returns False to end the game."""
        ui.show_standings(self.players)
        while True:
            answer = ui.safe_input(
                "\n [Enter] next hand · say <text> to chat · q to quit > ").strip()
            low = answer.lower()
            if low in ("q", "quit", "exit"):
                return False
            if low.startswith("say"):
                text = answer[3:].strip()
                if text:
                    self.table_talk(self.human, text)
                else:
                    ui.out(ui.dim("   usage: say <something>"))
                continue
            return True

    def handle_rebuys(self):
        """Nobody leaves the table: broke players are restaked by the house
        and the loan goes on their tab."""
        for p in self.players:
            if p.stack > 0:
                continue
            p.debt += self.starting_stack
            p.stack = self.starting_stack
            line = None if p.is_human else getattr(p, "personality", {}).get("broke_line")
            ui.announce_rebuy(p, self.starting_stack, p.debt, line)
            self.pause(0.6)

    # ------------------------------------------------------------- table talk

    def table_talk(self, speaker, text):
        """Broadcast a chat line and let a few AIs answer immediately."""
        text = text.strip()[:140]
        self.chat.append((speaker.name, text))
        self.chat = self.chat[-12:]
        ais = [p for p in self.players if p is not speaker and hasattr(p, "brain")]
        lower = text.lower()
        mentioned = [p for p in ais
                     if any(len(w) >= 3 and w.lower() != "the" and w.lower() in lower
                            for w in p.name.split())]
        others = [p for p in ais if p not in mentioned]
        self.rng.shuffle(others)
        responders = (mentioned + others[:max(0, 2 - len(mentioned))])[:3]
        for p in responders:
            reply = p.brain.chat_reply(p, self.chat_situation(p), list(self.chat),
                                       speaker.name, text)
            if reply:
                self.chat.append((p.name, reply))
                self.chat = self.chat[-12:]
                ui.chat_line(p.name, reply)
                self.pause(0.5)

    def chat_situation(self, p):
        if self.hand_live:
            board_txt = " ".join(str(c) for c in self.board) if self.board else "(none)"
            parts = ["Hand #%d, street %s, board: %s, pot: %d."
                     % (self.hand_no, self.street, board_txt, self.pot_total())]
            if p in self.hand_players and p.folded:
                parts.append("You have folded this hand.")
            elif p in self.hand_players and p.hole:
                parts.append("Your hole cards (secret): %s."
                             % " ".join(str(c) for c in p.hole))
        else:
            parts = ["Between hands (hand #%d just ended)." % self.hand_no]
        parts.append("Your stack: %d." % p.stack)
        if p.debt:
            parts.append("Your debt to the house: %d." % p.debt)
        return " ".join(parts)

    # ------------------------------------------------------------- one hand

    def play_hand(self):
        self.hand_live = True
        try:
            self._play_hand()
        finally:
            self.hand_live = False

    def _play_hand(self):
        self.hand_no += 1
        self.board = []
        self.history = []
        # self.chat deliberately persists across hands: conversation continues.
        self.revealed = False
        self.hand_players = list(self.players)
        for p in self.hand_players:
            p.reset_for_hand()

        seats = self.hand_players
        n = len(seats)
        self.button_idx %= n
        ui.hand_banner(self.hand_no, self.sb, self.bb, seats[self.button_idx].name)

        # Blinds. Heads-up: the button posts the small blind and acts first preflop.
        if n == 2:
            sb_i, bb_i = self.button_idx, (self.button_idx + 1) % n
        else:
            sb_i, bb_i = (self.button_idx + 1) % n, (self.button_idx + 2) % n
        self.street = "PREFLOP"
        self.new_street()
        for idx, blind, label in ((sb_i, self.sb, "small blind"), (bb_i, self.bb, "big blind")):
            paid = self.commit(seats[idx], blind)
            desc = "posts %s %d" % (label, paid)
            if seats[idx].all_in:
                desc += " (all-in)"
            self.record(seats[idx], desc)
            ui.announce_action(seats[idx], desc)
        self.current_bet = self.bb
        self.min_raise = self.bb

        # One card at a time around the table starting left of the button,
        # exactly like a live dealer. (With a uniform shuffle the order can't
        # favor a seat — this just makes the fairness self-evident.)
        deck = Deck(self.rng)
        for _ in range(2):
            for offset in range(1, n + 1):
                seats[(self.button_idx + offset) % n].hole.extend(deck.draw(1))
        human = self.human
        if human is not None and human in seats:
            ui.out(" your cards: %s" % ui.cards_str(human.hole))

        # Betting streets.
        if self.betting_round((bb_i + 1) % n):
            for street, count in (("FLOP", 3), ("TURN", 1), ("RIVER", 1)):
                self.maybe_reveal()
                self.street = street
                self.board.extend(deck.draw(count))
                self.new_street()
                ui.street_banner(street, self.board, self.pot_total())
                self.pause(1.0)
                if not self.betting_round((self.button_idx + 1) % n):
                    return
            self.showdown()
        # betting_round returning False means the pot was already awarded on folds

    def new_street(self):
        for p in self.hand_players:
            p.bet_street = 0
        self.current_bet = 0
        self.min_raise = self.bb

    def maybe_reveal(self):
        if self.revealed:
            return
        in_hand = [p for p in self.hand_players if p.in_hand]
        actionable = [p for p in in_hand if not p.all_in]
        if len(in_hand) >= 2 and len(actionable) <= 1:
            self.revealed = True
            ui.reveal_hands(in_hand)
            self.pause(1.2)

    # ------------------------------------------------------------- betting

    def betting_round(self, start_idx):
        """Run one betting street. Returns False if the hand ended on folds."""
        seats = self.hand_players
        n = len(seats)
        acted = set()
        idx = start_idx
        guard = 0
        while True:
            guard += 1
            if guard > n * 60:
                raise RuntimeError("betting round failed to terminate")
            in_hand = [p for p in seats if p.in_hand]
            if len(in_hand) <= 1:
                self.award_on_folds(in_hand[0])
                return False
            actionable = [p for p in in_hand if not p.all_in]
            if not actionable:
                return True
            # A lone player with chips facing only all-ins (and owing nothing)
            # has nobody left to bet against: action is closed.
            if len(actionable) == 1 and actionable[0].bet_street >= self.current_bet:
                return True
            if all(p in acted and p.bet_street == self.current_bet for p in actionable):
                return True

            p = seats[idx % n]
            idx += 1
            if p.folded or p.all_in:
                continue
            if p in acted and p.bet_street == self.current_bet:
                continue

            action, say = p.decide(self.build_view(p))
            reopened, desc = self.apply_action(p, action)
            self.record(p, desc)
            if say:
                self.chat.append((p.name, say))
                self.chat = self.chat[-12:]
            ui.announce_action(p, desc, say)
            if not p.is_human:
                self.pause(0.6)
            if reopened:
                acted = set()
            acted.add(p)

    def apply_action(self, p, action):
        """Mutates state for one action. Returns (reopened_betting, description)."""
        to_call = self.current_bet - p.bet_street
        kind = action.kind

        if kind == FOLD:
            p.folded = True
            return False, "folds"
        if kind == CHECK:
            if to_call <= 0:
                return False, "checks"
            kind = CALL  # illegal check downgraded to a call
        if kind == CALL:
            amount = min(to_call, p.stack)
            if amount <= 0:
                return False, "checks"
            self.commit(p, amount)
            return False, ("calls %d (all-in)" % amount) if p.all_in else ("calls %d" % amount)

        # RAISE or ALL_IN — both expressed as "raise the street total to `target`".
        max_to = p.bet_street + p.stack
        if kind == ALL_IN:
            target = max_to
        else:
            target = min(int(action.amount or 0), max_to)
            min_to = self.current_bet + self.min_raise
            if target < min_to:
                target = min(min_to, max_to)

        chips = target - p.bet_street
        if chips <= 0:
            return False, "checks"
        previous_bet = self.current_bet
        self.commit(p, chips)

        reopened = False
        if target > previous_bet:
            raise_size = target - previous_bet
            if raise_size >= self.min_raise:
                self.min_raise = raise_size
                reopened = True
            self.current_bet = target
            if p.all_in:
                desc = "goes ALL-IN for %d" % target
            elif previous_bet == 0:
                desc = "bets %d" % target
            else:
                desc = "raises to %d" % target
        else:
            desc = "calls %d and is all-in" % chips
        return reopened, desc

    # ------------------------------------------------------------- views

    def build_view(self, p):
        board = list(self.board)
        to_call = max(0, self.current_bet - p.bet_street)
        max_to = p.bet_street + p.stack
        min_to = min(self.current_bet + self.min_raise, max_to)
        can_raise = max_to > self.current_bet and p.stack > to_call

        hint = None
        if board and p.hole:
            rank, _ = evaluator.best_hand(p.hole + board)
            hint = evaluator.hand_name(rank)

        players_info = []
        for i, pl in enumerate(self.hand_players):
            players_info.append({
                "name": pl.name,
                "stack": pl.stack,
                "debt": pl.debt,
                "bet_street": pl.bet_street,
                "folded": pl.folded,
                "all_in": pl.all_in,
                "is_hero": pl is p,
                "is_button": i == self.button_idx,
                "is_human": pl.is_human,
            })

        return {
            "hand_no": self.hand_no,
            "street": self.street,
            "blinds": (self.sb, self.bb),
            "board": board,
            "pot": self.pot_total(),
            "to_call": to_call,
            "min_raise_to": min_to,
            "max_raise_to": max_to,
            "can_raise": can_raise,
            "hero": {
                "name": p.name,
                "stack": p.stack,
                "bet_street": p.bet_street,
                "committed": p.committed,
                "hole": list(p.hole),
            },
            "hero_hand_hint": hint,
            "players": players_info,
            "history": list(self.history),
            "chat": list(self.chat),
            "memory": list(self.memory),
            "broadcast": lambda text: self.table_talk(p, text),
        }

    # ------------------------------------------------------------- payouts

    def award_on_folds(self, winner):
        total = self.pot_total()
        winner.stack += total
        ui.out("")
        ui.announce_pot("%s wins the pot of %d — everyone else folded." % (winner.name, total))
        self.memory.append("Hand %d: %s won %d without a showdown (everyone folded)."
                           % (self.hand_no, winner.name, total))
        self.memory = self.memory[-8:]
        self.pause(1.0)

    def showdown(self):
        contenders = [p for p in self.hand_players if p.in_hand]
        results = {p: evaluator.best_hand(p.hole + self.board) for p in contenders}
        ui.show_showdown(contenders, results, self.revealed)
        self.pause(1.2)

        summaries = self.award_pots(contenders, results)
        for text in summaries:
            ui.announce_pot(text)
        if summaries:
            self.memory.append("Hand %d: %s" % (self.hand_no, summaries[0]))
            self.memory = self.memory[-8:]
        self.pause(1.2)

    def award_pots(self, contenders, results):
        """Split the money into main/side pots and pay the winners.

        Pot slices are defined by the distinct all-in commitment levels of the
        contenders; folded players' chips still count toward each slice.
        """
        summaries = []
        levels = sorted({p.committed for p in contenders})
        previous = 0
        pot_label = "main pot"
        for i, level in enumerate(levels):
            # The top slice absorbs everything left in the pot, including any
            # chips folded players committed beyond the contenders' caps.
            cap = level if i < len(levels) - 1 else None
            amount = sum((min(pl.committed, cap) if cap is not None else pl.committed)
                         - min(pl.committed, previous)
                         for pl in self.hand_players)
            previous = level
            if amount <= 0:
                continue
            eligible = [p for p in contenders if p.committed >= level]
            if len(eligible) == 1:
                # Nobody could match this slice — return the uncalled chips.
                eligible[0].stack += amount
                summaries.append("%s takes back %d uncalled chips." % (eligible[0].name, amount))
                continue
            best = max(results[p][0] for p in eligible)
            winners = [p for p in eligible if results[p][0] == best]
            share = amount // len(winners)
            remainder = amount - share * len(winners)
            for w in winners:
                w.stack += share
            for i in range(remainder):
                winners[i].stack += 1
            name = evaluator.hand_name(best)
            if len(winners) == 1:
                summaries.append("%s wins the %s of %d with %s."
                                 % (winners[0].name, pot_label, amount, name))
            else:
                summaries.append("%s split the %s of %d with %s."
                                 % (" and ".join(w.name for w in winners), pot_label, amount, name))
            pot_label = "side pot"
        return summaries
