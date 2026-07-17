"""One hand, start to finish: dealing, the betting streets, showdown and
side-pot payouts, and the strongest-first result panel."""

from __future__ import annotations

from .. import evaluator, ui
from ..cards import Deck
from ..players import ALL_IN, CALL, CHECK, FOLD, RAISE


class HandFlowMixin:
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
        self.shown = set()
        self.hand_winnings = {}
        self.hand_actions = []
        self.hero_advice = None
        self.advice_log = []
        self.hero_odds_payload = None
        self._odds_cache = {}
        self._odds_shown = None
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
        self.update_hero_odds()

        # Betting streets. A round returning False means everyone folded and
        # the pot has already been awarded; either way the hand is finished, so
        # every path falls through to the result panel at the bottom.
        if self.betting_round((bb_i + 1) % n):
            for street, count in (("FLOP", 3), ("TURN", 1), ("RIVER", 1)):
                self.maybe_reveal()
                self.street = street
                self.board.extend(deck.draw(count))
                self.new_street()
                ui.street_banner(street, self.board, self.pot_total())
                self.update_hero_odds()
                if not self.betting_round((self.button_idx + 1) % n):
                    break
            else:
                self.showdown()
        self.show_hand_result()
        self.advisor_verdict()   # the coach finds out whether it was right
        self.coach_review()      # ...and debriefs the whole hand, on the record

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
            self.shown.update(p.name for p in in_hand)
            ui.reveal_hands(in_hand)

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

            if p.is_human:
                # Folds since the last look change what you're up against.
                self.update_hero_odds()
            view = self.build_view(p)
            if p.is_human:
                view["advice"] = self.update_hero_advice(view)
            action, say = p.decide(view)
            reopened, desc, event = self.apply_action(p, action)
            self.hand_actions.append(dict(event, name=p.name, street=self.street,
                                          desc=desc))
            self.record(p, desc)
            ui.announce_action(p, desc)
            if p.is_human:
                self.note_hero_move(view, action, desc)
            if say:
                self.deliver_chat(p, say, in_action=True)
            else:
                # Moves draw comments too, not just words — the bigger the
                # move, the more likely someone has something to say about it.
                self.react_to_event(p, "%s %s." % (p.name, desc),
                                    self.reaction_chance(desc))
            if reopened:
                acted = set()
            acted.add(p)

    def apply_action(self, p, action):
        """Mutates state for one action.

        Returns (reopened_betting, description, event) — `event` is what
        actually happened after any clamping, structured, so the advisor can
        read the table from the real moves instead of parsing the sentences we
        print about them.
        """
        to_call = self.current_bet - p.bet_street
        kind = action.kind
        pot_before = self.pot_total()

        def done(reopened, desc, kind, amount):
            return reopened, desc, {"kind": kind, "amount": amount,
                                    "pot": pot_before}

        if kind == FOLD:
            p.folded = True
            return done(False, "folds", "fold", 0)
        if kind == CHECK:
            if to_call <= 0:
                return done(False, "checks", "check", 0)
            kind = CALL  # illegal check downgraded to a call
        if kind == CALL:
            amount = min(to_call, p.stack)
            if amount <= 0:
                return done(False, "checks", "check", 0)
            self.commit(p, amount)
            desc = ("calls %d (all-in)" % amount) if p.all_in else ("calls %d" % amount)
            return done(False, desc, "call", amount)

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
            return done(False, "checks", "check", 0)
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
                desc, event_kind = "goes ALL-IN for %d" % target, "all_in"
            elif previous_bet == 0:
                desc, event_kind = "bets %d" % target, "bet"
            else:
                desc, event_kind = "raises to %d" % target, "raise"
        else:
            desc, event_kind = "calls %d and is all-in" % chips, "call"
        return done(reopened, desc, event_kind, chips)

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
            # The hurry-up flag: the human has folded, so a brain may answer on
            # instinct instead of spending a model call on a pot they left.
            "fast": self.hero_out(),
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
            # The same moves as `history`, structured — what the advisor reads
            # opponents from, and cheap for a brain to ignore.
            "actions": list(self.hand_actions),
            "history": list(self.history),
            "chat": list(self.chat),
            "memory": list(self.memory),
            "broadcast": lambda text: self.table_talk(p, text),
        }

    # ------------------------------------------------------------- payouts

    def award_on_folds(self, winner):
        total = self.pot_total()
        winner.stack += total
        self.hand_winnings[winner.name] = self.hand_winnings.get(winner.name, 0) + total
        ui.out("")
        ui.announce_pot("%s wins the pot of %d — everyone else folded." % (winner.name, total))
        self.memory.append("Hand %d: %s won %d without a showdown (everyone folded)."
                           % (self.hand_no, winner.name, total))
        self.memory = self.memory[-8:]
        self.react_to_event(winner, "%s just won the pot of %d because everyone folded."
                            % (winner.name, total), 0.12)

    def showdown(self):
        contenders = [p for p in self.hand_players if p.in_hand]
        results = {p: evaluator.best_hand(p.hole + self.board) for p in contenders}
        self.shown.update(p.name for p in contenders)
        ui.show_showdown(contenders, results, self.revealed)

        summaries = self.award_pots(contenders, results)
        for text in summaries:
            ui.announce_pot(text)
        if summaries:
            self.memory.append("Hand %d: %s" % (self.hand_no, summaries[0]))
            self.memory = self.memory[-8:]
            # A showdown occasionally gets a word — kept rare for speed.
            self.react_to_event(None, "Showdown result: %s" % summaries[0], 0.2)

    def credit(self, player, amount):
        """Book chips a seat collected this hand, so the result panel can show
        who actually got paid without re-reading the announcements."""
        if amount:
            self.hand_winnings[player.name] = (
                self.hand_winnings.get(player.name, 0) + amount)

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
                self.credit(eligible[0], amount)
                summaries.append("%s takes back %d uncalled chips." % (eligible[0].name, amount))
                continue
            best = max(results[p][0] for p in eligible)
            winners = [p for p in eligible if results[p][0] == best]
            share = amount // len(winners)
            remainder = amount - share * len(winners)
            for w_i, w in enumerate(winners):
                got = share + (1 if w_i < remainder else 0)  # odd chips off the top
                w.stack += got
                self.credit(w, got)
            name = evaluator.hand_name(best)
            if len(winners) == 1:
                summaries.append("%s wins the %s of %d with %s."
                                 % (winners[0].name, pot_label, amount, name))
            else:
                summaries.append("%s split the %s of %d with %s."
                                 % (" and ".join(w.name for w in winners), pot_label, amount, name))
            pot_label = "side pot"
        return summaries

    # ------------------------------------------------------ the finished hand

    def show_hand_result(self):
        """Lay the finished hand out strongest first: what each seat held, the
        formula it came to, and the exact five cards that played.

        A seat's cards are only in there if they're genuinely public — it went
        to showdown, it's the human's own hand, or peek mode is on. Mucked
        hands stay mucked, so this can run after every hand without leaking
        anything the table didn't already see.
        """
        rows = []
        for p in self.hand_players:
            if not p.hole:
                continue
            known = self.reveal_all or p.is_human or p.name in self.shown
            rank = five = name = None
            if known and len(p.hole) + len(self.board) >= 5:
                rank, five = evaluator.best_hand(p.hole + self.board)
                name = evaluator.hand_name(rank)
            rows.append({
                "player": p,
                "known": known,
                "folded": p.folded,
                "won": self.hand_winnings.get(p.name, 0),
                "hole": list(p.hole) if known else [],
                "best5": five,
                "hand": name,
                "rank": rank,
            })
        # Strongest hand first; anything mucked sinks to the bottom.
        rows.sort(key=lambda r: (r["known"], r["rank"] or ()), reverse=True)
        ui.hand_result(self.hand_no, rows, list(self.board))

    def shown_ranks(self):
        """Hands the human could legitimately work out for themselves: the ones
        that were actually shown (plus everything, in peek mode). The coach
        judges itself on what the table saw — never on the mucked cards."""
        out = {}
        if len(self.board) < 5:
            return out
        for p in self.hand_players:
            if not p.hole:
                continue
            if self.reveal_all or p.name in self.shown:
                out[p.name] = evaluator.best_hand(p.hole + self.board)[0]
        return out
