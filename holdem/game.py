"""No-Limit Texas Hold'em engine."""

import random
import re
import threading

from . import advisor, evaluator, odds, ui
from .cards import Deck
from .players import Action, ALL_IN, CALL, CHECK, FOLD, RAISE

# Phrases that mean "justify your play" rather than idle banter.
# English and Chinese cues live in one list — the human may type either.
_STRONG_QUESTION = ("why", "how come", "how could", "how can", "explain",
                    "reasoning", "your logic", "justify", "what were you",
                    "what made you", "walk me through", "what was that",
                    "makes no sense", "make sense", "your thinking",
                    "what are you thinking", "how is that",
                    "为什么", "为啥", "凭什么", "解释", "说说你", "怎么想",
                    "什么逻辑", "讲讲", "什么意思", "图什么", "想什么")
_PLAY_WORDS = ("move", "bet", "raise", "call", "fold", "check", "all in", "all-in",
               "shove", "jam", "bluff", "play", "do that", "did that", "that for",
               "line", "hand",
               "加注", "跟注", "弃牌", "全下", "下注", "过牌", "这手", "那手",
               "这把", "那把", "唬", "诈")


def looks_like_move_question(text):
    """True if `text` is questioning a decision (deserves a reasoned answer),
    not just needling."""
    low = text.lower()
    if any(cue in low for cue in _STRONG_QUESTION):
        return True
    return ("?" in low or "？" in low) and any(w in low for w in _PLAY_WORDS)


class TexasHoldemGame:
    def __init__(self, players, sb=10, bb=20, rng=None, interactive=True,
                 reveal_all=False, language="en", show_odds=True, advisor=None):
        self.players = list(players)  # seat order; only players with chips
        self.sb = sb
        self.bb = bb
        self.rng = rng if rng is not None else random.SystemRandom()
        self.interactive = interactive
        self.reveal_all = reveal_all  # peek mode: show every hand once it's over
        self.language = language      # what the agents speak ("en" / "zh")
        self.show_odds = show_odds    # live equity read for the human seat
        # The coach behind the player's chair (holdem/advisor.py), or None for
        # nobody. It needs the equity numbers, so it can't work without them.
        self.advisor = advisor if show_odds else None
        self.starting_stack = players[0].stack if players else 0
        self.button_idx = 0
        self.hand_no = 0
        self.memory = []  # one-line summaries of past hands, fed to the AIs
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

    def ai_buy_ins(self):
        """Before the next hand, each AI seat decides for itself whether to top
        up — buying up to one starting stack from the house, which goes on its
        tab. LLM seats genuinely weigh it (only when below a full buy-in);
        offline seats go on instinct."""
        cap = self.starting_stack
        table = self.buy_context()
        weighing = [p for p in self.players
                    if not p.is_human and hasattr(p, "brain")
                    and getattr(p.brain, "is_llm", False)
                    and p.stack < self.starting_stack]
        if weighing:
            ui.out(ui.dim("   (the table weighs topping up…)"))
        for p in self.players:
            if p.is_human or not hasattr(p, "brain"):
                continue
            want = p.brain.buy_decision(p, cap, self.starting_stack, table)
            amount = self.grant_chips(p, min(int(want or 0), cap))
            if amount:
                ui.announce_buy(p, amount, p.debt)

    def buy_context(self):
        """Compact between-hands snapshot for the top-up decision: blinds, the
        current standings (by net), and recent-hand memory."""
        return {
            "blinds": (self.sb, self.bb),
            "standings": [(p.name, p.stack, p.debt) for p in
                          sorted(self.players, key=lambda x: -(x.stack - x.debt))],
            "memory": list(self.memory),
        }

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
            key = "broke_line_zh" if self.language == "zh" else "broke_line"
            persona = getattr(p, "personality", {}) or {}
            line = None if p.is_human else (persona.get(key) or persona.get("broke_line"))
            ui.announce_rebuy(p, self.starting_stack, p.debt, line)

    # ------------------------------------------------------------- table talk

    GROUP_CUES = ("everyone", "everybody", "you all", "y'all", "you guys",
                  "you two", "all of you", "anyone", "anybody", "guys", "folks",
                  "大家", "各位", "你们", "所有人", "兄弟们", "诸位")

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
        """Entry point for a spoken line (human `say` or between-hands chat).
        Safe to call from any thread — a web front-end calls it out-of-band so
        the human can speak whenever they like, and the table still answers."""
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
        with self.talk_lock:
            self._deliver_chat_locked(speaker, text, in_action, solicit, force_to)

    def _deliver_chat_locked(self, speaker, text, in_action, solicit, force_to):
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
                parts.append("You have folded this hand — still, keep your cards to "
                             "yourself until the hand is over.")
            elif p in self.hand_players and p.hole:
                parts.append("Your hole cards (SECRET — the hand is live, so do NOT "
                             "reveal them to anyone; bluff or say nothing): %s."
                             % " ".join(str(c) for c in p.hole))
        else:
            parts = ["Between hands (hand #%d just ended — you may be honest about "
                     "what you held now if you like)." % self.hand_no]
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
            stance = ("You're still contesting this hand." if p in self.hand_players
                      and not p.folded else "You've folded, but the hand isn't finished yet.")
            parts.append("%s The hand is STILL LIVE, so you must NOT reveal your exact hole "
                         "cards to anyone — keep them secret or bluff, but never state what you "
                         "truly hold until the hand is over. Your reasoning must still be real "
                         "and coherent." % stance)
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

    # ------------------------------------------------------- the human's read

    def update_hero_odds(self):
        """Recompute and show the human's live read: the hand they hold right
        now, every hand they can still get to, and what each is worth. Only the
        human gets this — the agents reason from their own view, and handing
        them a solver would make them something else entirely."""
        if not self.show_odds:
            return
        human = self.human
        if human is None or human not in self.hand_players:
            return
        if human.folded or len(human.hole) < 2:
            return
        live = sum(1 for p in self.hand_players if p is not human and not p.folded)
        if live < 1:
            return
        key = (tuple(str(c) for c in human.hole),
               tuple(str(c) for c in self.board), live)
        if key == self._odds_shown:
            return  # nothing has moved — don't say the same thing twice
        payload = self._odds_cache.get(key)
        if payload is None:
            payload = odds.hand_odds(human.hole, self.board, live, self.rng)
            if payload is None:
                return
            self._odds_cache[key] = payload
        # Kept even when the read hasn't changed: the advisor needs the numbers
        # every time it's asked, not just when they're worth re-announcing.
        self.hero_odds_payload = payload
        if key == self._odds_shown:
            return
        self._odds_shown = key
        ui.hero_odds(payload)

    # ------------------------------------------------------------ the coach

    def update_hero_advice(self, view):
        """Ask the coach to call this exact spot, and show what it says.

        Returns the advice so the turn can act on it (the follow button, the
        autopilot) and so we can tell afterwards whether it was taken.
        """
        if self.advisor is None or self.hero_odds_payload is None:
            return None
        advice = self.advisor.advise(view, self.hero_odds_payload)
        if advice is None:
            return None
        # Carry the command that enacts it, so the follow button, the autopilot
        # and the terminal can't drift into following it three different ways.
        advice["command"] = advisor.advice_command(advice)
        self.hero_advice = advice
        self.advice_log.append({"street": self.street, "advice": advice,
                                "action": None, "desc": None, "followed": None})
        ui.advice(advice)
        return advice

    def note_hero_move(self, view, action, desc):
        """Record what the player actually did against what they were told —
        and if they went their own way, let the coach say so now rather than
        pretend it didn't notice."""
        if not self.advice_log:
            return
        entry = self.advice_log[-1]
        if entry["action"] is not None:
            return  # this advice has already been answered
        advice = entry["advice"]
        entry["action"] = action
        entry["desc"] = desc
        entry["followed"] = advisor.followed_advice(advice, action)
        if entry["followed"] or self.advisor is None:
            return
        line = self.advisor.on_defiance(advice, action, view)
        if line:
            ui.advisor_line(line, "defiance")

    def advisor_verdict(self):
        """The hand is over: the coach finds out whether it was right, and has
        to say so out loud."""
        if self.advisor is None or not self.advice_log:
            return
        context = self.verdict_context(self.advice_log[-1])
        if context is None:
            return
        tone, line = self.advisor.verdict(context)
        if line:
            ui.advisor_verdict(line, tone, context)

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

    def verdict_context(self, entry):
        human = self.human
        if human is None or not human.hole:
            return None
        net = self.hand_winnings.get(human.name, 0) - human.committed
        told_fold = entry["advice"]["action"] == FOLD

        hero_rank = None
        if len(human.hole) + len(self.board) >= 5:
            hero_rank = evaluator.best_hand(human.hole + self.board)[0]
        others = {n: r for n, r in self.shown_ranks().items() if n != human.name}
        would_have_won = None
        if hero_rank is not None and others:
            would_have_won = hero_rank >= max(others.values())

        # Was the advice right? Judged on what actually happened, which is what
        # a player wants from a coach — not on whether it was +EV in theory.
        if human.folded:
            # Nobody showed anything, so nobody gets to claim they were right.
            right = None if would_have_won is None else (
                (not would_have_won) if told_fold else would_have_won)
        elif net > 0:
            right = not told_fold
        elif net < 0:
            right = told_fold
        else:
            right = None

        return {
            "followed": bool(entry["followed"]),
            "advice": entry["advice"],
            "action_desc": entry["desc"] or "did nothing",
            "net": net,
            "right": right,
            "folded": human.folded,
            "would_have_won": would_have_won,
            "hero_hand": evaluator.hand_name(hero_rank) if hero_rank else None,
            "winner_hand": (evaluator.hand_name(max(others.values()))
                            if others else None),
        }

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
