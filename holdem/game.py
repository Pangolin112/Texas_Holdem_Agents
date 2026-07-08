"""No-Limit Texas Hold'em engine."""

import random
import re

from . import evaluator, ui
from .cards import Deck
from .players import Action, ALL_IN, CALL, CHECK, FOLD, RAISE

# Phrases that mean "justify your play" rather than idle banter.
_STRONG_QUESTION = ("why", "how come", "how could", "how can", "explain",
                    "reasoning", "your logic", "justify", "what were you",
                    "what made you", "walk me through", "what was that",
                    "makes no sense", "make sense", "your thinking",
                    "what are you thinking", "how is that")
_PLAY_WORDS = ("move", "bet", "raise", "call", "fold", "check", "all in", "all-in",
               "shove", "jam", "bluff", "play", "do that", "did that", "that for",
               "line", "hand")


def looks_like_move_question(text):
    """True if `text` is questioning a decision (deserves a reasoned answer),
    not just needling."""
    low = text.lower()
    if any(cue in low for cue in _STRONG_QUESTION):
        return True
    return "?" in low and any(w in low for w in _PLAY_WORDS)


class TexasHoldemGame:
    def __init__(self, players, sb=10, bb=20, rng=None, interactive=True,
                 reveal_all=False):
        self.players = list(players)  # seat order; only players with chips
        self.sb = sb
        self.bb = bb
        self.rng = rng if rng is not None else random.SystemRandom()
        self.interactive = interactive
        self.reveal_all = reveal_all  # peek mode: show every hand once it's over
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
            if self.reveal_all:
                # Cards still hold this hand's deal — reset happens next hand.
                ui.reveal_all_hands(self.hand_players, self.board)
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

    def ai_buy_ins(self):
        """Before the next hand, each AI seat may top up its own stack — buying
        up to one starting stack from the house, which goes on its tab. A local
        economic call per seat, no API round-trips."""
        cap = self.starting_stack
        for p in self.players:
            if p.is_human or not hasattr(p, "brain"):
                continue
            want = p.brain.buy_decision(p, cap, self.starting_stack)
            amount = self.grant_chips(p, min(int(want or 0), cap))
            if amount:
                ui.announce_buy(p, amount, p.debt)

    def human_buy(self, arg, allowance):
        """The human tops up their own stack. Chips are added to the stack and
        to the tab (net worth unchanged). Returns the amount actually bought."""
        human = self.human
        if human is None:
            return 0
        if allowance <= 0:
            ui.out(ui.dim("   you've already topped up the max for this hand."))
            return 0
        digits = "".join(ch for ch in arg if ch.isdigit())
        if not digits:
            ui.out(ui.dim("   usage: buy <amount>  (1–%d chips, added to your stack and your tab)"
                          % allowance))
            return 0
        amount = int(digits)
        if amount <= 0:
            return 0
        if amount > allowance:
            ui.out(ui.dim("   capped at %d more this hand — buying that." % allowance))
            amount = allowance
        self.grant_chips(human, amount)
        ui.announce_buy(human, amount, human.debt)
        return amount

    def grant_chips(self, player, amount):
        """Sell chips from the house: added to the stack and put on the tab, so
        net worth (stack - debt) is unchanged — it's a loan for more ammunition
        on the table. Returns the amount granted."""
        amount = max(0, int(amount or 0))
        if amount:
            player.stack += amount
            player.debt += amount
        return amount

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

    # ------------------------------------------------------------- table talk

    GROUP_CUES = ("everyone", "everybody", "you all", "y'all", "you guys",
                  "you two", "all of you", "anyone", "anybody", "guys", "folks")

    def player_by_name(self, name):
        for p in self.players:
            if p.name == name:
                return p
        return None

    def resolve_addressee(self, speaker, text):
        """Who is this line aimed at? Returns a list of players (empty = the
        whole table): players named in the text; else, for a bare "you",
        whoever the speaker is most plausibly replying to."""
        lower = text.lower()
        others = [p for p in self.players if p is not speaker]
        named = [p for p in others
                 if any(len(w) >= 3 and w.lower() != "the"
                        and re.search(r"\b%s\b" % re.escape(w.lower()), lower)
                        for w in p.name.split())]
        if named:
            return named
        if any(cue in lower for cue in self.GROUP_CUES):
            return []
        if re.search(r"\byou\b|\byours?\b", lower):
            partner = self.last_interlocutor(speaker)
            if partner is not None:
                return [partner]
        return []

    def last_interlocutor(self, speaker):
        """The most recent other voice in the conversation, or failing that
        the last other player to act in this hand."""
        for name, _to, _text in reversed(self.chat):
            if name != speaker.name:
                return self.player_by_name(name)
        if self.hand_live:
            for _street, line in reversed(self.history):
                for p in self.hand_players:
                    if p is not speaker and line.startswith(p.name + " "):
                        return p
        return None

    def table_talk(self, speaker, text):
        """Entry point for a spoken line (human `say` or between-hands chat)."""
        self.deliver_chat(speaker, text)

    def reaction_chance(self, desc):
        # Kept low on purpose: every reaction is another model call to wait on.
        if "ALL-IN" in desc or "all-in" in desc:
            return 0.22
        if desc.startswith(("raises", "bets")):
            return 0.10
        if desc.startswith("calls"):
            return 0.03
        return 0.015  # checks, folds

    def react_to_event(self, actor, event, chance):
        """Once in a while a single bystander drops a one-off comment on a move
        or result. It's a one-shot — nobody replies to it — to keep the pace up."""
        if self.rng.random() >= chance:
            return
        candidates = [pl for pl in self.players
                      if pl is not actor and hasattr(pl, "brain")]
        if not candidates:
            return
        reactor = self.rng.choice(candidates)
        line = reactor.brain.react(reactor, self.chat_situation(reactor),
                                   list(self.chat), event)
        if line:
            self.deliver_chat(reactor, line, in_action=True, solicit=False)

    def deliver_chat(self, speaker, text, in_action=False, solicit=True,
                     force_to=None, max_len=140):
        """Record one chat line, resolve whom it addresses, and show it. When
        `solicit`, let at most ONE player answer (and that answer does not draw
        another) so a single remark never balloons into many model calls."""
        text = " ".join(text.split())[:max_len]
        if not text:
            return
        if force_to is not None:
            addressees = [force_to]
            to_name = force_to.name
        else:
            addressees = self.resolve_addressee(speaker, text)
            to_name = addressees[0].name if len(addressees) == 1 else None
        self.chat.append((speaker.name, to_name, text))
        self.chat = self.chat[-12:]
        ui.chat_line(speaker.name, text, to_name)
        if not solicit:
            return
        responder = next((p for p in addressees if hasattr(p, "brain")), None)
        if responder is None and not in_action:
            # A line to the whole table: one random voice may answer, no more.
            others = [p for p in self.players
                      if p is not speaker and hasattr(p, "brain")]
            self.rng.shuffle(others)
            responder = others[0] if others else None
        if responder is None:
            return
        # Questioning a seat's own move earns a reasoned explanation, not banter.
        if responder in addressees and looks_like_move_question(text):
            answer = responder.brain.explain_move(
                responder, self.explain_context(responder),
                list(self.chat), speaker.name, text)
            if answer:
                self.deliver_chat(responder, answer, in_action=in_action,
                                  solicit=False, force_to=speaker, max_len=500)
            return
        addressed = "you" if responder in addressees else to_name
        reply = responder.brain.chat_reply(responder, self.chat_situation(responder),
                                           list(self.chat), speaker.name, text, addressed)
        if reply:
            # The reply is a dead end — it doesn't itself provoke a response.
            self.deliver_chat(responder, reply, in_action=in_action, solicit=False)

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

    def explain_context(self, p):
        """Rich context for justifying a move: the state, this seat's own cards,
        whether the hand is still live (so it knows if it may keep cards secret),
        and the full action log to reason over."""
        parts = []
        if self.hand_live:
            board_txt = " ".join(str(c) for c in self.board) if self.board else "(none)"
            parts.append("Right now: hand #%d, %s, board %s, pot %d, your stack %d."
                         % (self.hand_no, self.street, board_txt, self.pot_total(), p.stack))
            parts.append("Your own hole cards: %s."
                         % (" ".join(str(c) for c in p.hole) if p.hole else "(none dealt)"))
            if p in self.hand_players and not p.folded:
                parts.append("This hand is STILL LIVE and you're still in it — you may keep "
                             "your exact cards to yourself, but your reasoning must be real.")
            else:
                parts.append("You're out of this hand now, so you can speak freely and honestly.")
        else:
            parts.append("The last hand (#%d) just finished — you can be fully honest about it."
                         % self.hand_no)
            if p.hole:
                parts.append("Your cards were: %s." % " ".join(str(c) for c in p.hole))
        parts.append("Action log of the hand:\n" + self._history_text())
        if p.debt:
            parts.append("Your debt to the house: %d." % p.debt)
        return "\n".join(parts)

    def _history_text(self):
        if not self.history:
            return "  (no betting action recorded yet)"
        return "\n".join("  [%s] %s" % (street, text) for street, text in self.history)

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
            ui.announce_action(p, desc)
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
        self.react_to_event(winner, "%s just won the pot of %d because everyone folded."
                            % (winner.name, total), 0.12)

    def showdown(self):
        contenders = [p for p in self.hand_players if p.in_hand]
        results = {p: evaluator.best_hand(p.hole + self.board) for p in contenders}
        ui.show_showdown(contenders, results, self.revealed)

        summaries = self.award_pots(contenders, results)
        for text in summaries:
            ui.announce_pot(text)
        if summaries:
            self.memory.append("Hand %d: %s" % (self.hand_no, summaries[0]))
            self.memory = self.memory[-8:]
            # A showdown occasionally gets a word — kept rare for speed.
            self.react_to_event(None, "Showdown result: %s" % summaries[0], 0.2)

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
