"""Self-contained test suite (stdlib only): python test_game.py"""

import random

from holdem import evaluator, ui
from holdem.brains import PERSONALITIES, HeuristicBrain, LLMBrain
from holdem.cards import Card, Deck, RANK_VALUES
from holdem.game import TexasHoldemGame
from holdem.players import Action, LLMPlayer, Player, ALL_IN, CALL, CHECK, FOLD, RAISE

ui.QUIET = True

CHECKS = {"passed": 0}


def ok(condition, label):
    assert condition, "FAILED: %s" % label
    CHECKS["passed"] += 1


def cards(text):
    """'As Kd 7c' -> [Card, ...]"""
    return [Card(RANK_VALUES[t[0].upper()], t[1].lower()) for t in text.split()]


def rank(text):
    return evaluator.evaluate_five(cards(text))


# --------------------------------------------------------------- evaluator

def test_evaluator():
    ok(rank("As Ks Qs Js Ts")[0] == 8, "royal flush detected")
    ok(rank("5h 4h 3h 2h Ah") == (8, 5), "steel wheel is a 5-high straight flush")
    ok(rank("9c 9d 9h 9s 2c")[0] == 7, "quads detected")
    ok(rank("9c 9d 9h 2s 2c")[0] == 6, "full house detected")
    ok(rank("Ah 9h 7h 5h 2h")[0] == 5, "flush detected")
    ok(rank("9c 8d 7h 6s 5c") == (4, 9), "straight detected")
    ok(rank("5d 4c 3h 2s Ac") == (4, 5), "wheel straight, ace plays low")
    ok(rank("Ad Kc Qh Js Tc") == (4, 14), "broadway straight")
    ok(rank("9c 9d 9h Ks 2c")[0] == 3, "trips detected")
    ok(rank("9c 9d Kh Ks 2c")[0] == 2, "two pair detected")
    ok(rank("9c 9d Kh Qs 2c")[0] == 1, "pair detected")
    ok(rank("Ac 9d Kh Qs 2c")[0] == 0, "high card detected")

    ok(rank("Ah 9h 7h 5h 2h") > rank("9c 8d 7h 6s 5c"), "flush beats straight")
    ok(rank("9c 9d 9h 2s 2c") > rank("Ah 9h 7h 5h 2h"), "full house beats flush")
    ok(rank("9c 9d Kh Ks Ac") > rank("9c 9d Kh Ks Qc"), "two-pair kicker breaks tie")
    ok(rank("Ac Ad 3h 4s 5c") > rank("Kc Kd Ah Qs Jc"), "pair of aces beats pair of kings")
    ok(rank("6c 5d 4h 3s 2c") > rank("5d 4c 3h 2s Ac"), "6-high straight beats the wheel")

    best_rank, best_five = evaluator.best_hand(cards("As Ks 2c 7d Qs Js Ts"))
    ok(best_rank == (8, 14), "best_hand finds the royal flush in 7 cards")
    ok(len(best_five) == 5, "best_hand returns exactly five cards")
    ok(evaluator.hand_name((6, 14, 13)) == "a Full House, Aces over Kings", "hand naming")
    ok(evaluator.hand_name((1, 6)) == "a Pair of Sixes", "six pluralizes as sixes")


# --------------------------------------------------------------- scripted players

class ScriptedPlayer(Player):
    def __init__(self, name, stack, script=()):
        super().__init__(name, stack)
        self.script = list(script)

    def decide(self, view):
        assert self.script, "%s was asked to act with an empty script" % self.name
        return self.script.pop(0), None


def make_game(players, **kwargs):
    kwargs.setdefault("rng", random.Random(7))
    kwargs.setdefault("fast", True)
    kwargs.setdefault("interactive", False)
    return TexasHoldemGame(players, **kwargs)


def test_fold_around():
    # Seats: P0 button, P1 SB, P2 BB, P3 UTG. Everyone folds; BB keeps the blinds.
    p = [ScriptedPlayer("P0", 1000, [Action(FOLD)]),
         ScriptedPlayer("P1", 1000, [Action(FOLD)]),
         ScriptedPlayer("P2", 1000),
         ScriptedPlayer("P3", 1000, [Action(FOLD)])]
    game = make_game(p)
    game.play_hand()
    ok(p[2].stack == 1010, "big blind collects the small blind")
    ok(p[1].stack == 990, "small blind lost 10")
    ok(p[0].stack == 1000 and p[3].stack == 1000, "folders lost nothing")


def test_raise_call_and_min_raise():
    # P3 raises to 60, P0 re-raises to 140, others fold, P3 calls -> flop.
    # Then both check it down to showdown.
    p = [ScriptedPlayer("P0", 1000, [Action(RAISE, 140)] + [Action(CHECK)] * 3),
         ScriptedPlayer("P1", 1000, [Action(FOLD)]),
         ScriptedPlayer("P2", 1000, [Action(FOLD)]),
         ScriptedPlayer("P3", 1000, [Action(RAISE, 60), Action(CALL)] + [Action(CHECK)] * 3)]
    game = make_game(p)
    game.play_hand()
    ok(sum(pl.stack for pl in p) == 4000, "chips conserved through raise war")
    ok(p[1].stack == 990 and p[2].stack == 980, "blinds forfeited by folders")
    ok(p[0].stack + p[3].stack == 2030 or (p[0].stack == p[3].stack == 1015),
       "the 280 pot (plus blinds) went to the showdown players")


def test_min_raise_clamping():
    # A raise below the legal minimum gets bumped up to the minimum.
    p = [ScriptedPlayer("P0", 1000, [Action(RAISE, 25)]),  # min raise-to is 40
         ScriptedPlayer("P1", 1000, [Action(FOLD)]),
         ScriptedPlayer("P2", 1000, [Action(FOLD)])]
    game = make_game(p)
    game.play_hand()
    ok(p[0].stack == 1000 + 30, "undersized raise was clamped to the legal minimum and won blinds")


def test_all_in_showdown_conserves_chips():
    p = [ScriptedPlayer("P0", 500, [Action(ALL_IN)]),
         ScriptedPlayer("P1", 800, [Action(CALL)]),
         ScriptedPlayer("P2", 1000, [Action(FOLD)]),
         ScriptedPlayer("P3", 1000, [Action(FOLD)])]
    game = make_game(p)
    game.play_hand()
    ok(sum(pl.stack for pl in p) == 3300, "chips conserved through all-in runout")
    ok(p[2].stack == 980 and p[3].stack == 1000, "non-participants only lost blinds")
    ok(p[0].stack + p[1].stack == 1320, "all-in pot settled between the two players")


def rigged_showdown(committed, holes, board, folded=()):
    """Build a game frozen at showdown time and let it pay the pots."""
    players = [Player("P%d" % i, 0) for i in range(len(committed))]
    game = make_game(players)
    game.hand_players = players
    game.board = cards(board)
    for i, pl in enumerate(players):
        pl.committed = committed[i]
        pl.hole = cards(holes[i]) if holes[i] else []
        pl.folded = i in folded
    contenders = [pl for pl in players if not pl.folded]
    results = {pl: evaluator.best_hand(pl.hole + game.board) for pl in contenders}
    game.award_pots(contenders, results)
    return players


def test_side_pots():
    # A is all-in short with the best hand; B has second-best; C worst; D folded.
    players = rigged_showdown(
        committed=[100, 300, 300, 50],
        holes=["As Ad", "Ks Kd", "Qs Qd", ""],
        board="2h 5c 7s 9d Jc",
        folded=(3,),
    )
    # Main pot: 100+100+100+50 = 350 to A. Side pot: 200+200 = 400 to B.
    ok(players[0].stack == 350, "short all-in wins only the main pot")
    ok(players[1].stack == 400, "second-best hand wins the side pot")
    ok(players[2].stack == 0, "worst hand gets nothing")


def test_uncalled_chips_returned():
    players = rigged_showdown(
        committed=[500, 300],
        holes=["2s 7d", "As Ad"],
        board="3h 5c 8s 9d Jc",
    )
    # B wins 600 pot; A takes back the 200 nobody called.
    ok(players[1].stack == 600, "caller wins the matched pot")
    ok(players[0].stack == 200, "overbet returned uncalled")


def test_split_pot_with_odd_chip():
    players = rigged_showdown(
        committed=[100, 100, 101],
        holes=["Ah Kd", "As Kc", ""],
        board="2h 5c 7s 9d Kh",
        folded=(2,),
    )
    ok(players[0].stack + players[1].stack == 301, "split pot pays out fully")
    ok(abs(players[0].stack - players[1].stack) <= 1, "odd chip split off by at most one")


# --------------------------------------------------------------- llm parsing

class FakeView(dict):
    pass


def parse_view(to_call=50, can_raise=True):
    return {"to_call": to_call, "can_raise": can_raise,
            "min_raise_to": 100, "max_raise_to": 900}


def test_llm_parsing():
    brain = LLMBrain(client=None, model="x", personality=PERSONALITIES[0],
                     rng=random.Random(1))
    action, say = brain._parse('{"action": "raise", "raise_to": 30, "say": "yeehaw"}',
                               parse_view())
    ok(action.kind == RAISE and action.amount == 100, "undersized LLM raise clamped to minimum")
    ok(say == "yeehaw", "table talk extracted")

    action, _ = brain._parse('{"action": "raise", "raise_to": 5000}', parse_view())
    ok(action.kind == RAISE and action.amount == 900, "oversized LLM raise clamped to all-in")

    action, _ = brain._parse('{"action": "check"}', parse_view(to_call=50))
    ok(action.kind == CALL, "illegal check becomes a call")

    action, _ = brain._parse('{"action": "fold"}', parse_view(to_call=0))
    ok(action.kind == CHECK, "pointless fold becomes a free check")

    action, _ = brain._parse('Sure! Here you go: {"action": "all_in", "say": ""}',
                             parse_view())
    ok(action.kind == ALL_IN, "JSON extracted from chatty reply")

    try:
        brain._parse("I fold I guess", parse_view())
        ok(False, "garbage reply should raise")
    except ValueError:
        ok(True, "garbage reply raises for fallback to handle")


# --------------------------------------------------------------- fairness

def test_deck_integrity():
    rng = random.Random(3)
    for _ in range(500):
        deck = Deck(rng)
        assert len({(c.value, c.suit) for c in deck.cards}) == 52
    ok(True, "500 shuffles: always 52 unique cards, no duplicates possible")


def test_deal_fairness():
    """Round-robin dealing off a uniform shuffle must not favor any seat."""
    rng = random.Random(2026)
    seats = 6
    deals = 20000
    value_sum = [0] * seats
    aces = [0] * seats
    for _ in range(deals):
        deck = Deck(rng)
        cards_out = deck.draw(2 * seats)
        for i, card in enumerate(cards_out):
            seat = i % seats  # one card at a time around the table
            value_sum[seat] += card.value
            if card.value == 14:
                aces[seat] += 1
    expected_mean = sum(range(2, 15)) / 13.0  # 8.0
    for seat in range(seats):
        mean = value_sum[seat] / float(deals * 2)
        assert abs(mean - expected_mean) < 0.1, "seat %d mean %.3f" % (seat, mean)
    expected_aces = deals * 2 / 13.0
    for seat in range(seats):
        assert abs(aces[seat] - expected_aces) < 250, "seat %d aces %d" % (seat, aces[seat])
    ok(True, "20k deals x 6 seats: card values and aces evenly distributed")


def test_system_random_games():
    """The secure OS-entropy RNG must work through the whole engine."""
    rng = random.SystemRandom()
    deck = Deck(rng)
    ok(len({(c.value, c.suit) for c in deck.cards}) == 52, "SystemRandom shuffles a full deck")
    roster = rng.sample(PERSONALITIES, 4)
    players = [LLMPlayer(pers["name"], 1000, pers, HeuristicBrain(pers, rng))
               for pers in roster]
    game = TexasHoldemGame(players, rng=rng, fast=True, interactive=False)
    game.run(max_hands=15)
    total = sum(pl.stack for pl in game.players)
    debts = sum(pl.debt for pl in game.players)
    ok(total == 4000 + debts, "chips = buy-ins + house loans across SystemRandom hands")


# --------------------------------------------------------------- rebuys & chat

def test_rebuy_adds_debt_nobody_leaves():
    p = [Player("A", 1000), Player("B", 1000)]
    game = make_game(p)
    p[0].stack = 0
    game.handle_rebuys()
    ok(p[0].stack == 1000 and p[0].debt == 1000, "broke player restaked, loan on the tab")
    ok(len(game.players) == 2, "nobody is removed from the table")
    p[0].stack = 0
    game.handle_rebuys()
    ok(p[0].debt == 2000, "debts accumulate across rebuys")
    ok(p[1].debt == 0, "solvent players owe nothing")


def talk_game(names, seed=11):
    rng = random.Random(seed)
    by_name = {p["name"]: p for p in PERSONALITIES}
    players = [LLMPlayer(n, 1000, by_name[n], HeuristicBrain(by_name[n], rng))
               for n in names]
    return make_game(players, rng=rng), players


def test_addressee_resolution():
    game, p = talk_game(["Mike", "Sarah", "Emma", "Ray"])
    mike, sarah, emma, ray = p
    ok(game.resolve_addressee(mike, "nice bluff, Emma") == [emma],
       "a name in the line resolves to that player")
    ok(game.resolve_addressee(mike, "Ray, nice hand") == [ray],
       "short names resolve too")
    ok(game.resolve_addressee(mike, "that was crazy") == [],
       "names inside other words don't count (crazy != Ray)")
    ok(game.resolve_addressee(mike, "you guys are way too quiet") == [],
       "group words mean the whole table")
    game.chat = [("Sarah", None, "big talk from the small stack")]
    ok(game.resolve_addressee(mike, "you wish") == [sarah],
       "a bare 'you' resolves to whoever the speaker is answering")
    ok(game.resolve_addressee(sarah, "what a night") == [],
       "no cue means talking to the table")
    got = game.resolve_addressee(ray, "Mike and Sarah, you two should slow down")
    ok(set(x.name for x in got) == {"Mike", "Sarah"},
       "several names resolve to several people")


def test_table_talk_gets_replies():
    game, players = talk_game(["Mike", "Sarah", "Emma"])
    speaker = players[0]
    game.table_talk(speaker, "you all play scared, especially you Sarah")
    entry = game.chat[0]
    ok(entry == (speaker.name, "Sarah",
                 "you all play scared, especially you Sarah"),
       "the line is logged with the resolved addressee")
    repliers = [name for name, _to, _text in game.chat[1:]]
    ok("Sarah" in repliers, "the agent addressed by name answers")
    ok(all(s != t for s, t, _x in game.chat), "nobody talks to themselves")
    game.hand_players = list(players)
    view = game.build_view(players[1])
    ok(view["chat"] == game.chat, "agents see the conversation in their view")


def test_move_reactions():
    game, players = talk_game(["Mike", "Sarah", "Emma"], seed=2)
    mike = players[0]
    ok(game.reaction_chance("goes ALL-IN for 900") > game.reaction_chance("raises to 60")
       > game.reaction_chance("checks"),
       "bigger moves draw comments more often")
    for _ in range(5):  # heuristic reactors stay quiet sometimes; a few rolls suffice
        game.react_to_event(mike, "Mike goes ALL-IN for 900.", chance=1.0)
        if game.chat:
            break
    ok(len(game.chat) >= 1, "a bystander comments on a big move")
    ok(game.chat[0][0] != "Mike", "the comment comes from someone else, not the actor")
    before = len(game.chat)
    game.react_to_event(mike, "Mike checks.", chance=0.0)
    ok(len(game.chat) == before, "chance 0 means silence")


def test_agents_answer_each_other():
    game, players = talk_game(["Mike", "Sarah", "Emma"], seed=5)
    mike = players[0]
    # An agent (not the human) addresses another agent: she can answer him.
    game.deliver_chat(mike, "Sarah, that raise of yours was ridiculous", in_action=True)
    repliers = [name for name, _to, _text in game.chat[1:]]
    ok("Sarah" in repliers, "an agent answers another agent, not just the human")
    ok(len(game.chat) <= 6, "exchanges stay bounded — no infinite chatter")
    for entry in game.chat:
        ok(len(entry) == 3, "every chat entry carries speaker, addressee, text")


# --------------------------------------------------------------- fuzz

def test_fuzz_full_games():
    for seed in range(30):
        rng = random.Random(seed)
        n = rng.choice([2, 3, 4, 5, 6])
        roster = rng.sample(PERSONALITIES, n)
        players = [LLMPlayer(pers["name"], 1000, pers, HeuristicBrain(pers, rng))
                   for pers in roster]
        game = TexasHoldemGame(players, rng=rng, fast=True, interactive=False)
        buyins = n * 1000
        for _ in range(60):
            game.play_hand()
            got = sum(pl.stack for pl in game.players)
            debts = sum(pl.debt for pl in game.players)
            assert got == buyins + debts, ("seed %d hand %d: chips %d != buyins %d + debts %d"
                                           % (seed, game.hand_no, got, buyins, debts))
            game.handle_rebuys()
            game.button_idx = (game.button_idx + 1) % len(game.players)
    ok(True, "30 seeded multi-hand games: chips always equal buy-ins plus house loans")


if __name__ == "__main__":
    test_evaluator()
    test_fold_around()
    test_raise_call_and_min_raise()
    test_min_raise_clamping()
    test_all_in_showdown_conserves_chips()
    test_side_pots()
    test_uncalled_chips_returned()
    test_split_pot_with_odd_chip()
    test_llm_parsing()
    test_deck_integrity()
    test_deal_fairness()
    test_system_random_games()
    test_rebuy_adds_debt_nobody_leaves()
    test_addressee_resolution()
    test_table_talk_gets_replies()
    test_move_reactions()
    test_agents_answer_each_other()
    test_fuzz_full_games()
    print("all good: %d checks passed" % CHECKS["passed"])
