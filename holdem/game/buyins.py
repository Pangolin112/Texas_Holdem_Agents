"""Between-hands chip management: voluntary top-ups and the house rebuy that
means nobody is ever eliminated."""

from __future__ import annotations

from .. import ui


class BuyInsMixin:
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
