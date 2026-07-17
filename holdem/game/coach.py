"""The coach's integration into the hand: live equity reads, per-turn advice,
grading what the player actually did, and the post-hand debrief."""

from __future__ import annotations

from .. import advisor, evaluator, odds, ui
from ..players import FOLD


class CoachMixin:
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

    def farewell_payload(self):
        """The night in numbers, for the send-off at the door."""
        human = self.human
        if human is None:
            return None
        return {
            "name": human.name,
            "hands": self.hand_no,
            "net": human.stack - human.debt - self.starting_stack,
            "stack": human.stack,
            "debt": human.debt,
            "starting_stack": self.starting_stack,
            "session": dict(self.coach_session,
                            mistakes=dict(self.coach_session["mistakes"])),
        }

    def farewell(self):
        """The player is leaving — the coach walks them to the door.

        Called by the front-ends on their way out (the terminal after the run
        ends, the web app when the Leave button is clicked), not by the engine
        loop: leaving is a front-end event, but what gets said is the engine's
        business. Never raises — a failed goodbye must not block the exit.
        """
        payload = self.farewell_payload()
        if payload is None:
            return
        text = None
        if self.advisor is not None:
            try:
                text = self.advisor.send_off(payload)
            except Exception:
                text = None
        payload["text"] = text
        ui.farewell(payload)

    def coach_review(self):
        """The whole hand, debriefed: every advised decision graded against the
        numbers it was made with, folded into the session ledger, and handed to
        the coach to talk about — the hand's process, and the player's habits.
        """
        if self.advisor is None:
            return
        human = self.human
        if human is None or not human.hole:
            return
        entries = [e for e in self.advice_log if e["action"] is not None]
        if not entries:
            return
        net = self.hand_winnings.get(human.name, 0) - human.committed
        rows = []
        for e in entries:
            adv = e["advice"]
            rows.append({
                "street": e["street"],
                "advised": {"action": adv["action"], "amount": adv.get("amount") or 0},
                "did": e["desc"],
                "followed": bool(e["followed"]),
                "grade": advisor.grade_decision(adv, e["action"]),
                "equity": adv["adjusted"],
                "price": adv["pot_odds"],
                "danger": adv.get("danger"),
            })

        s = self.coach_session
        s["hands"] += 1
        s["decisions"] += len(rows)
        s["followed"] += sum(1 for r in rows if r["followed"])
        s["net"] += net
        # A hand's result is attributed to whether they listened THAT hand —
        # one defiance owns the outcome, since one wrong turn is all it takes.
        if all(r["followed"] for r in rows):
            s["net_followed"] += net
        else:
            s["net_defied"] += net
        for r in rows:
            if r["grade"]:
                s["mistakes"][r["grade"]] = s["mistakes"].get(r["grade"], 0) + 1

        ctx = {
            "hand_no": self.hand_no,
            "net": net,
            "decisions": rows,
            "session": dict(s, mistakes=dict(s["mistakes"])),
            # One quick decision on a tiny pot doesn't deserve model prose —
            # the fallback's canned line covers it, free.
            "worth_prose": len(rows) >= 2 or abs(net) >= 5 * self.bb,
        }
        text = self.advisor.review(ctx)
        ui.hand_review({"hand_no": self.hand_no, "net": net, "decisions": rows,
                        "session": ctx["session"], "text": text})

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
