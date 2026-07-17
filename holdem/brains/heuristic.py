"""The default offline seat: aggression/looseness scalars, no API, no learning."""

from __future__ import annotations

from .. import evaluator
from ..players import Player, PlayerView, ActionKind, FOLD, CHECK, CALL, RAISE, ALL_IN
from .policy import PolicyBrain, preflop_strength


class HeuristicBrain(PolicyBrain):
    """The default offline seat. Its whole character is two hand-tuned scalars,
    `aggression` and `looseness`, that weight how it reads its hand and how it
    scores each action — no learning, no API. The strongest available offline
    play, and the fallback whenever an LLM seat's API call fails."""

    # -- strength estimation ------------------------------------------------

    def _preflop_strength(self, hole):
        return preflop_strength(hole)

    def _strength(self, hole, board):
        if not board:
            return self._preflop_strength(hole)
        rank, _ = evaluator.best_hand(hole + board)
        base = {0: 0.15, 1: 0.38, 2: 0.55, 3: 0.66, 4: 0.76,
                5: 0.82, 6: 0.91, 7: 0.97, 8: 0.99}[rank[0]]
        # Don't get excited about a made hand that is entirely on the board.
        if len(board) == 5:
            board_rank, _ = evaluator.best_hand(board)
            if board_rank >= rank:
                base = 0.25
        return max(0.05, min(0.99, base + (self.rng.random() - 0.5) * 0.12))

    # -- action scoring -----------------------------------------------------

    def _action_utilities(self, player: Player, view: PlayerView,
                          strength: float) -> list[tuple[ActionKind, float]]:
        to_call = view["to_call"]
        pot = max(view["pot"], 1)
        aggr = self.p["aggression"]
        loose = self.p["looseness"]
        can_raise = view["can_raise"]
        bb = view["blinds"][1]

        # Looser players talk themselves into more hands, so they perceive more
        # strength than is really there.
        eff = strength + (loose - 0.5) * 0.22
        # A short stack pushes with anything half-decent, folds the rest.
        short_push = 2.5 * (strength - 0.5) if player.stack <= 6 * bb else 0.0
        # Aggression + looseness together are the bluff/steal appetite.
        bluff = aggr * loose

        utils: list[tuple[ActionKind, float]] = []
        if to_call == 0:
            utils.append((CHECK, 0.5))
            if can_raise:
                utils.append((RAISE,
                              2.0 * (strength - 0.5) + 1.3 * (aggr - 0.5)
                              + 0.63 * bluff))
            utils.append((ALL_IN, 3.0 * (strength - 0.9) + short_push))
        else:
            pot_odds = to_call / float(pot + to_call)
            margin = eff - pot_odds  # >0 means the price is right
            utils.append((FOLD, 0.6 * (pot_odds - eff) * (1.6 - loose) - 0.15))
            utils.append((CALL, 1.4 * margin + 0.35 * loose + 0.15))
            if can_raise:
                utils.append((RAISE,
                              2.2 * (strength - 0.55) + 1.3 * (aggr - 0.5)
                              + 0.9 * bluff))
            utils.append((ALL_IN, 3.0 * (strength - 0.85) + short_push))
        return utils
