"""WebSink: the presenter the engine talks to on the game thread. Turns every
game event into a browser message and blocks for human input over a queue."""

from __future__ import annotations

import queue
import re

from holdem import evaluator, ui
from holdem.ui import QuitGame

from .util import _QUIT, _strip_ansi, cards_data


class WebSink(ui.Sink):
    """Turns engine events into browser messages and blocks for human input.

    Every event carries a full `state` snapshot rebuilt from the live game, so
    the browser can always render the whole table (bots acting, cards dealing)
    even between the player's own turns — and a reconnecting tab catches up
    instantly.
    """

    def __init__(self, session, game):
        self.session = session
        self.game = game
        self.face_up = set()   # names whose hole cards are currently public
        self.legal = None      # cached legal-move info for the player's turn

    # -- state snapshot -----------------------------------------------------

    def snapshot(self):
        g = self.game
        live = g.hand_live
        human = g.human
        seats = []
        for i, p in enumerate(g.players):
            show = (p is human) or (p.name in self.face_up)
            seats.append({
                "name": p.name,
                "stack": p.stack,
                "debt": p.debt,
                "net": p.stack - p.debt,
                "bet": p.bet_street if live else 0,
                "committed": p.committed if live else 0,
                # folded stays true between hands so the summary can dim seats
                # that mucked; all-in badge is dropped once the hand is over.
                "folded": p.folded,
                "all_in": p.all_in if live else False,
                "is_human": p.is_human,
                "is_button": (i == g.button_idx),
                "card_count": len(p.hole),
                "cards": cards_data(p.hole) if (show and p.hole) else None,
            })
        # The human's best hand right now, recomputed on every event so the
        # readout tracks the board card by card instead of only on their turn.
        # Before the flop there's no five-card hand to name, so it carries the
        # preflop shape instead — "pocket nines" is still an answer.
        hero_hand = None
        if human is not None and human.hole:
            if len(human.hole) + len(g.board) >= 5:
                rank, five = evaluator.best_hand(list(human.hole) + list(g.board))
                hero_hand = {"name": evaluator.hand_name(rank), "cat": rank[0],
                             "cards": cards_data(five), "preflop": False}
            else:
                shape = evaluator.starting_hand(human.hole)
                if shape is not None:
                    hero_hand = {"name": shape["name"], "cat": None,
                                 "kind": shape["kind"],
                                 "cards": cards_data(human.hole), "preflop": True}
        return {
            "hand_no": g.hand_no,
            "street": g.street if live else None,
            "live": live,
            "sb": g.sb,
            "bb": g.bb,
            "button": g.button_idx,
            # the board object is only cleared when the next hand starts, so it
            # persists between hands as the finished-hand summary on the felt.
            "board": cards_data(g.board),
            "pot": g.pot_total() if live else 0,
            "current_bet": g.current_bet if live else 0,
            "starting_stack": g.starting_stack,
            "hero_name": human.name if human else None,
            "hero_hand": hero_hand,
            "hero_folded": bool(human.folded) if human else False,
            "hero_auto": getattr(human, "auto", None) if human else None,
            "seats": seats,
        }

    def send(self, event_type, **data):
        data["type"] = event_type
        data.setdefault("state", self.snapshot())
        self.session.emit(data)

    # -- output events (mirror holdem.ui) -----------------------------------

    def out(self, text):
        text = _strip_ansi(text).strip()
        if text:
            self.send("log", text=text)

    def warn(self, text):
        self.send("log", level="warn", text=_strip_ansi(text).strip())

    def title_screen(self):
        pass  # the browser draws its own title

    def show_help(self):
        pass  # the browser has its own help panel

    def hand_banner(self, hand_no, sb, bb, dealer_name):
        self.face_up = set()  # a fresh deal — nothing is public yet
        self.legal = None
        self.send("hand_start", hand_no=hand_no, sb=sb, bb=bb, dealer=dealer_name)

    def street_banner(self, street, board, pot):
        self.send("street", street=street, board=cards_data(board), pot=pot)

    def chat_line(self, name, text, to):
        self.send("chat", name=name, text=text, to=to)

    def announce_action(self, player, desc):
        self.send("action", name=player.name, desc=desc)

    def thinking(self, name):
        self.send("thinking", name=name)

    def reveal_hands(self, players):
        for p in players:
            self.face_up.add(p.name)
        self.send("reveal", reason="all-in",
                  players=[{"name": p.name, "cards": cards_data(p.hole)} for p in players])

    def show_showdown(self, contenders, results, already_revealed):
        for p in contenders:
            self.face_up.add(p.name)
        rows = []
        for p in contenders:
            rank, _best5 = results[p]
            rows.append({"name": p.name, "cards": cards_data(p.hole),
                         "hand": evaluator.hand_name(rank)})
        self.send("showdown", players=rows)

    def hand_result(self, hand_no, rows, board):
        out_rows = []
        for row in rows:
            p = row["player"]
            if row["known"]:
                # Anything the panel shows is public now — leave it face up on
                # the felt too, until the next deal clears it.
                self.face_up.add(p.name)
            out_rows.append({
                "name": p.name,
                "is_human": p.is_human,
                "known": row["known"],
                "folded": row["folded"],
                "won": row["won"],
                "cards": cards_data(row["hole"]) if row["known"] else None,
                "best5": cards_data(row["best5"]) if row["best5"] else None,
                "hand": row["hand"],
                "cat": row["rank"][0] if row["rank"] else None,
            })
        self.send("hand_result", hand_no=hand_no, board=cards_data(board),
                  players=out_rows)

    def hero_odds(self, payload):
        data = dict(payload)
        made = payload.get("made")
        if made:
            # Pass every field the engine sent through — only the cards need
            # converting. Listing the keys here instead would silently drop any
            # new one (it already ate the preflop shape once).
            data["made"] = dict(made, cards=cards_data(made["cards"]))
        self.send("odds", odds=data)

    def advice(self, payload):
        self.send("advice", advice=payload)

    def advisor_line(self, text, kind):
        self.send("advisor_line", text=text, kind=kind)

    def advisor_verdict(self, text, tone, context):
        context = context or {}
        self.send("advisor_verdict", text=text, tone=tone,
                  followed=bool(context.get("followed")), net=context.get("net"))

    def hand_review(self, review):
        self.send("hand_review", review=review)

    def farewell(self, payload):
        self.send("farewell", farewell=payload)

    def autopilot(self, player, mode):
        self.send("autopilot", name=player.name, mode=mode)

    def announce_pot(self, text):
        self.send("pot_award", text=_strip_ansi(text).strip())

    def announce_buy(self, player, amount, debt):
        self.send("buy", name=player.name, amount=amount, debt=debt)

    def announce_rebuy(self, player, stake, debt, line):
        self.send("rebuy", name=player.name, stake=stake, debt=debt, line=line)

    def show_standings(self, players, title):
        rows = [{"name": p.name, "stack": p.stack, "debt": p.debt,
                 "net": p.stack - p.debt, "is_human": p.is_human}
                for p in sorted(players, key=lambda x: -(x.stack - x.debt))]
        self.send("standings", title=title, rows=rows)

    # -- the player's turn: stash legal info, then block for a command ------

    def show_table(self, view):
        hero = view["hero"]
        self.legal = {
            "to_call": view["to_call"],
            "min_raise_to": view["min_raise_to"],
            "max_raise_to": view["max_raise_to"],
            "can_raise": view["can_raise"],
            "hero_hand_hint": view.get("hero_hand_hint"),
            "hero_stack": hero["stack"],
            "hero_bet": hero["bet_street"],
            "pot": view["pot"],
        }

    def input(self, prompt):
        mode, extra = self._classify(prompt)
        event = {"type": "await", "mode": mode, "prompt": prompt.strip(),
                 "state": self.snapshot()}
        event.update(extra)
        self.session.pending_await = event
        self.session.outbound.put(event)
        try:
            while self.session.alive:
                try:
                    line = self.session.inbound.get(timeout=0.5)
                except queue.Empty:
                    continue
                if line is _QUIT:
                    raise QuitGame
                return line
            raise QuitGame
        finally:
            self.session.pending_await = None

    def _classify(self, prompt):
        low = prompt.lower()
        if "your move" in low:
            return "action", {"legal": self.legal or {}}
        if "next hand" in low:
            allowance = 0
            m = re.search(r"up to (\d+)", low)
            if m:
                allowance = int(m.group(1))
            return "between", {"allowance": allowance}
        return "text", {}
