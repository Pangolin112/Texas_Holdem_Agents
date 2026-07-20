"""Table talk: who a line is aimed at, who answers, and the one-reply rule
that keeps a single remark from ballooning into a chain of model calls."""

from __future__ import annotations

import re

from .. import ui

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


class ChatMixin:
    GROUP_CUES = ("everyone", "everybody", "you all", "y'all", "you guys",
                  "you two", "all of you", "anyone", "anybody", "guys", "folks",
                  "大家", "各位", "你们", "所有人", "兄弟们", "诸位")

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
        if self.hero_out():
            return  # fast-forward: no commentary on a hand the player left
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
        # Fast-forward: a bot's one-liner during a hand the player left must
        # not solicit a (model-priced) reply. The human's own words still draw
        # answers — they're watching, and they asked.
        if solicit and not speaker.is_human and self.hero_out():
            solicit = False
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
                         "truly hold until the hand is over. You don't owe anyone your real "
                         "thinking mid-hand either: deflect, or sell a story that serves your "
                         "game, as long as it stays coherent with how you've played." % stance)
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
