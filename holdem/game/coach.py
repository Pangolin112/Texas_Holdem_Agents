"""The coach's integration into the hand: live equity reads, per-turn advice,
grading what the player actually did, and the post-hand debrief.

The coach never blocks the game. Its work runs in a background task that
starts the moment a street begins (while the other seats are still acting),
and its output is published into the player's turn whenever it lands — the
instant arithmetic first, the model's refinement on top. The player can act
at any point; whatever the coach hadn't said yet is simply dropped.
"""

from __future__ import annotations

import threading

from .. import advisor, evaluator, odds, ui
from ..players import AUTO_ADVISOR, FOLD


class _AdviceTask:
    """One background run of the coach on one specific spot."""

    def __init__(self, key, view, payload, hand_no):
        self.key = key            # (hand, street, to_call, pot, live seats)
        self.view = view          # the snapshot the advice is computed from
        self.payload = payload    # the odds the advice is computed from
        self.hand_no = hand_no
        self.base = None          # the instant arithmetic call
        self.refined = None       # the model's refinement, when it lands
        self.published = None     # last advice object actually shown
        self.publish_view = None  # the live turn's view, once the turn claims us
        self.entry = None         # the advice_log entry created on publication
        self.cancelled = False
        self.done = threading.Event()


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

    def _advice_async(self):
        """True when the coach thinks over the wire — then it runs in the
        background. The arithmetic-only coach is instant and stays inline,
        which also keeps offline games (and the test suite) deterministic."""
        adv = self.advisor
        return (adv is not None and getattr(adv, "is_llm", False)
                and getattr(adv, "client", None) is not None)

    def _spot_key(self, view):
        live = tuple(sorted(p["name"] for p in view["players"]
                            if not p["is_hero"] and not p["folded"]))
        return (self.hand_no, view["street"], view["to_call"], view["pot"], live)

    def prewarm_advice(self):
        """Start the coach on the human's spot the moment a street begins —
        while the seats in front are still acting. If the action reaches the
        human unchanged (folds and checks don't change the spot), the answer
        is already there; if someone raises, the turn just starts a fresh one.
        """
        if not self._advice_async() or self.hero_odds_payload is None:
            return
        human = self.human
        if (human is None or human not in self.hand_players or human.folded
                or human.all_in or self.hero_out()):
            return
        self._start_advice_task(self.build_view(human))

    def _start_advice_task(self, view):
        task = _AdviceTask(self._spot_key(view), view, self.hero_odds_payload,
                           self.hand_no)
        with self.advice_lock:
            if self._advice_task is not None:
                self._advice_task.cancelled = True
            self._advice_task = task
        sink = ui.get_sink()  # the worker reports through this thread's sink
        threading.Thread(target=self._run_advice_task, args=(task, sink),
                         daemon=True).start()
        return task

    def _run_advice_task(self, task, sink):
        ui.set_sink(sink)
        try:
            task.base = self.advisor.base_advice(task.view, task.payload)
            with self.advice_lock:
                self._maybe_publish(task)   # the turn may already be waiting
            if task.cancelled or task.base is None:
                return
            refined = self.advisor.refine(task.view, task.payload, task.base)
            if refined is not None:
                task.refined = refined
                with self.advice_lock:
                    self._maybe_publish(task)
        except Exception:
            pass  # a failed coach run must never take the table down
        finally:
            task.done.set()
            ui.set_sink(None)

    def _maybe_publish(self, task):
        """Show the task's best answer on the pending turn. Caller holds
        advice_lock. Publishes at most once per distinct result: the base as
        soon as the turn claims the task, the refinement when it lands — and
        nothing at all once the player has already acted."""
        if task.cancelled or task is not self._advice_task:
            return
        view = task.publish_view
        if view is None:
            return  # the turn hasn't arrived — hold the answer until it does
        if task.hand_no != self.hand_no or not self.hand_live:
            return
        source = task.refined or task.base
        if source is None or source is task.published:
            return
        if task.entry is not None and task.entry["action"] is not None:
            return  # they've already moved; don't rewrite history
        task.published = source
        advice = dict(source)
        # Carry the command that enacts it, so the follow button, the autopilot
        # and the terminal can't drift into following it three different ways.
        advice["command"] = advisor.advice_command(advice)
        if task.entry is None:
            task.entry = {"street": self.street, "advice": advice,
                          "action": None, "desc": None, "followed": None}
            self.advice_log.append(task.entry)
        else:
            task.entry["advice"] = advice
        self.hero_advice = advice
        view["advice"] = advice
        ui.advice(advice)

    def update_hero_advice(self, view):
        """Get the coach onto this exact spot without making the player wait.

        Synchronous (and unchanged) for the arithmetic coach; for the model
        coach it claims the background task started at the top of the street —
        or starts a fresh one if the spot changed — and returns immediately.
        The answer is published into `view` and the panel whenever it lands.
        The one deliberate exception: with follow-the-coach armed, the move IS
        the coach's answer, so that path waits for it.
        """
        if self.advisor is None or self.hero_odds_payload is None:
            return None
        if not self._advice_async():
            return self._advise_sync(view)
        key = self._spot_key(view)
        with self.advice_lock:
            self.hero_advice = None   # never leave last street's call armable
            task = self._advice_task
            if task is not None and (task.cancelled or task.key != key):
                task.cancelled = True
                task = None
        if task is None:
            task = self._start_advice_task(view)
        with self.advice_lock:
            task.publish_view = view
            self._maybe_publish(task)
        human = self.human
        if human is not None and getattr(human, "auto", None) == AUTO_ADVISOR:
            # Delegation: "do whatever the coach says" has to hear the coach.
            task.done.wait(timeout=30.0)
            with self.advice_lock:
                self._maybe_publish(task)
        return view.get("advice")

    def _advise_sync(self, view):
        """The inline path: ask, log, show — exactly the old behavior."""
        advice = self.advisor.advise(view, self.hero_odds_payload)
        if advice is None:
            return None
        advice["command"] = advisor.advice_command(advice)
        self.hero_advice = advice
        self.advice_log.append({"street": self.street, "advice": advice,
                                "action": None, "desc": None, "followed": None})
        ui.advice(advice)
        view["advice"] = advice
        return advice

    def note_hero_move(self, view, action, desc):
        """Record what the player actually did against what they were told —
        and if they went their own way, let the coach say so now rather than
        pretend it didn't notice."""
        with self.advice_lock:
            if self._advice_task is not None:
                # The spot dies with the move: whatever the coach hadn't said
                # yet is about a street state that no longer exists.
                self._advice_task.cancelled = True
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
        # The defiance line can be a model call — never make it under the lock.
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
