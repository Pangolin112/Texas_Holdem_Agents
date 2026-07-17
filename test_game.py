"""Self-contained test suite (stdlib only): python test_game.py"""

import random

from holdem import evaluator, odds, ui
from holdem.brains import (PERSONALITIES, HeuristicBrain, LLMBrain, ModelChain,
                           PolicyBrain, spoken_action, _softmax)
from holdem.cards import Card, Deck, RANK_VALUES
from holdem.game import TexasHoldemGame, looks_like_move_question
from holdem.players import (Action, HumanPlayer, LLMPlayer, Player,
                            ALL_IN, AUTO_CALL, AUTO_CALL_STREET, AUTO_FOLD,
                            CALL, CHECK, FOLD, RAISE)

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


def test_fast_ranker_agrees_with_brute_force():
    """rank_cards reads the hand off rank/suit counts instead of trying all 21
    combinations. It's only allowed to exist because it agrees exactly."""
    rng = random.Random(99)
    deck = [Card(v, s) for v in RANK_VALUES.values() for s in "shdc"]
    for _ in range(4000):
        hand = rng.sample(deck, rng.choice([5, 6, 7]))
        fast = evaluator.rank_cards(hand)
        slow, _ = evaluator.best_hand(hand)
        assert fast == slow, ("%s: fast %s != brute force %s"
                              % (" ".join(str(c) for c in hand), fast, slow))
    ok(True, "4000 random 5/6/7-card deals: fast ranker matches brute force exactly")

    # The shapes worth naming, including the ones a counting evaluator trips on.
    ok(evaluator.rank_cards(cards("As Ks Qs Js Ts 2c 3d")) == (8, 14),
       "royal flush found among seven cards")
    ok(evaluator.rank_cards(cards("Ah 5h 4h 3h 2h Kd")) == (8, 5),
       "steel wheel: the ace drops to the bottom of a straight flush")
    ok(evaluator.rank_cards(cards("9c 9d 9h Ks Kd Kh 2c")) == (6, 13, 9),
       "two trips make a full house off the higher one")
    ok(evaluator.rank_cards(cards("Ks Kd 9h 9s 5c 5d 2c")) == (2, 13, 9, 5),
       "three pairs play the top two plus the best kicker")
    ok(evaluator.rank_cards(cards("As 8s 7s 5s 3s 2s Kd")) == (5, 14, 8, 7, 5, 3),
       "six of a suit plays the five highest")
    ok(evaluator.rank_cards(cards("9c 8d 7h 6s 5c 4d 2h")) == (4, 9),
       "the highest straight wins out of a six-card run")


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


def test_spoken_action_detection():
    # Clear first-person declarations.
    ok(spoken_action("I fold") == FOLD, "'I fold' -> fold")
    ok(spoken_action("alright, I'm folding") == FOLD, "'I'm folding' -> fold")
    ok(spoken_action("I call") == CALL, "'I call' -> call")
    ok(spoken_action("I'll call that") == CALL, "'I'll call' -> call")
    ok(spoken_action("I check") == CHECK, "'I check' -> check")
    ok(spoken_action("I raise") == RAISE, "'I raise' -> raise")
    ok(spoken_action("I'm raising this") == RAISE, "'I'm raising' -> raise")
    ok(spoken_action("I'm all in!") == ALL_IN, "'I'm all in' -> all-in")
    ok(spoken_action("all in baby") == ALL_IN, "bare 'all in' in own line -> all-in")
    ok(spoken_action("I'm shipping it") == ALL_IN, "'shipping it' -> all-in")
    ok(spoken_action("I shove") == ALL_IN, "'I shove' -> all-in")

    # Things that must NOT be read as the speaker's move.
    ok(spoken_action("") is None, "empty say -> no declaration")
    ok(spoken_action(None) is None, "None say -> no declaration")
    ok(spoken_action("nice call") is None, "'nice call' is praise, not a call")
    ok(spoken_action("you fold too much") is None, "'you fold' is about someone else")
    ok(spoken_action("you should just fold") is None, "advice to others isn't self-declaration")
    ok(spoken_action("are you all in?") is None, "a question isn't a declaration")
    ok(spoken_action("you going all in?") is None, "'you ... all in?' isn't self-declaration")
    ok(spoken_action("I'm not folding") is None, "negated fold -> no declaration")
    ok(spoken_action("I'm not going all in here") is None, "negated all-in -> no declaration")
    ok(spoken_action("I've got the nuts") is None, "a card bluff names no move")
    ok(spoken_action("maybe I fold, maybe not") is None, "hedged talk -> no declaration")
    ok(spoken_action("call or fold, tough spot") is None, "musing over options -> no declaration")

    # Negation lets the real, non-negated move win.
    ok(spoken_action("I'm not folding, I'm all in") == ALL_IN,
       "negated fold + real shove -> all-in")


def test_words_conform_to_moves():
    brain = LLMBrain(client=None, model="x", personality=PERSONALITIES[0],
                     rng=random.Random(1))

    # Speech overrides a contradicting mechanical action.
    action, say = brain._parse('{"action": "call", "say": "actually, I fold"}',
                               parse_view(to_call=50))
    ok(action.kind == FOLD, "says fold while action=call -> the move becomes fold")

    action, _ = brain._parse('{"action": "fold", "say": "I\'m all in!"}',
                             parse_view(to_call=50))
    ok(action.kind == ALL_IN, "says all-in while action=fold -> the move becomes all-in")

    action, _ = brain._parse('{"action": "call", "say": "you\'re bluffing, I raise"}',
                             parse_view(to_call=50))
    ok(action.kind == RAISE, "says raise while action=call -> the move becomes a raise")

    # Bluffing about CARDS never changes the move.
    action, say = brain._parse('{"action": "call", "say": "I flopped a set, easy call"}',
                               parse_view(to_call=50))
    ok(action.kind == CALL and "set" in say, "lying about your hand leaves the move alone")

    # Consistent pairs pass through untouched.
    action, _ = brain._parse('{"action": "raise", "raise_to": 200, "say": "I raise"}',
                             parse_view(to_call=50))
    ok(action.kind == RAISE and action.amount == 200, "matching word + move kept as-is")

    # Talk aimed at others doesn't hijack the move.
    action, _ = brain._parse('{"action": "all_in", "say": "you should fold, friend"}',
                             parse_view(to_call=50))
    ok(action.kind == ALL_IN, "advice to another player never changes your own move")

    # A move the speaker can't legally make: don't lie, drop the claim.
    action, say = brain._parse('{"action": "call", "say": "I raise big!"}',
                               parse_view(to_call=50, can_raise=False))
    ok(action.kind == CALL and say is None,
       "can't raise here -> keep legal move but drop the false 'I raise'")


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
    game = TexasHoldemGame(players, rng=rng, interactive=False)
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


def test_buy_chips_keeps_net_worth():
    p = [Player("A", 1000), Player("B", 1000)]
    game = make_game(p)
    net_before = p[0].stack - p[0].debt
    got = game.grant_chips(p[0], 300)
    ok(got == 300, "grant_chips returns the amount added")
    ok(p[0].stack == 1300 and p[0].debt == 300, "bought chips added to stack and to the tab")
    ok(p[0].stack - p[0].debt == net_before, "buying chips leaves net worth unchanged")
    ok(p[1].stack == 1000 and p[1].debt == 0, "other seats untouched by a top-up")


def test_buy_decision_capped_and_reloads_short_stacks():
    brain = HeuristicBrain(PERSONALITIES[0], random.Random(0))  # Mike: loose + aggressive
    full = 1000
    deep = Player("deep", 900)
    ok(brain.buy_decision(deep, full, full) == 0, "a still-deep stack stands pat")
    short = Player("short", 100)
    amounts = [brain.buy_decision(short, full, full) for _ in range(300)]
    ok(all(0 <= a <= full for a in amounts), "a top-up never exceeds the cap")
    ok(all(short.stack + a <= full for a in amounts), "a top-up never overshoots a full stack")
    ok(any(a > 0 for a in amounts), "a gambler does reload a short stack sometimes")


def test_llm_buy_decision_parses_and_clamps():
    brain = LLMBrain(client=None, model="x", personality=PERSONALITIES[0],
                     rng=random.Random(1))
    short = Player("z", 300)  # below a full buy-in -> the agent is actually asked
    brain._create = lambda messages, **kw: '{"buy": 400}'
    ok(brain.buy_decision(short, 1000, 1000) == 400, "LLM buy amount parsed")
    brain._create = lambda messages, **kw: '{"buy": 99999}'
    ok(brain.buy_decision(short, 1000, 1000) == 1000, "LLM buy amount clamped to the cap")
    brain._create = lambda messages, **kw: '{"buy": -50}'
    ok(brain.buy_decision(short, 1000, 1000) == 0, "a negative buy is floored at zero")

    # A comfortably full stack stands pat WITHOUT ever calling the model.
    def boom(*a, **k):
        raise AssertionError("a full stack must not spend a model call")
    brain._create = boom
    ok(brain.buy_decision(Player("full", 1000), 1000, 1000) == 0,
       "a full buy-in skips the decision entirely")

    # A model/parse failure falls back to the heuristic instead of crashing.
    def blow_up(*a, **k):
        raise RuntimeError("uplink down")
    brain._create = blow_up
    val = brain.buy_decision(Player("y", 100), 1000, 1000)
    ok(0 <= val <= 1000, "buy decision falls back to instinct on model error")


def test_ai_buy_ins_preserve_chip_invariant():
    rng = random.Random(1)
    roster = rng.sample(PERSONALITIES, 4)
    players = [LLMPlayer(pers["name"], 1000, pers, HeuristicBrain(pers, rng))
               for pers in roster]
    game = make_game(players, rng=rng)
    for pl in players:  # short-stack everyone so top-ups actually trigger
        pl.stack = 150
    game.ai_buy_ins()
    total = sum(pl.stack for pl in players)
    debts = sum(pl.debt for pl in players)
    ok(total == 600 + debts, "AI top-ups keep chips = on-table + house loans")
    ok(all(pl.debt <= 1000 for pl in players), "no seat buys more than one stack at once")


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


def test_move_question_detection():
    ok(looks_like_move_question("why did you fold there?"), "'why did you fold' -> question")
    ok(looks_like_move_question("Dave, explain that raise"), "'explain that raise' -> question")
    ok(looks_like_move_question("what were you thinking"), "'what were you thinking' -> question")
    ok(looks_like_move_question("how could you call that"), "'how could you call' -> question")
    ok(looks_like_move_question("was that a bluff?"), "'a bluff?' (question + play word) -> question")
    ok(not looks_like_move_question("nice hand"), "'nice hand' -> not a question")
    ok(not looks_like_move_question("you got lucky, Sarah"), "a needle -> not a question")
    ok(not looks_like_move_question("good game everyone"), "a pleasantry -> not a question")


def test_questioning_a_move_gets_a_reasoned_answer():
    game, players = talk_game(["Mike", "Sarah", "Emma"], seed=4)
    asker = players[0]
    game.deliver_chat(asker, "Sarah, why did you raise there?", in_action=True)
    ok(game.chat[0][0] == asker.name, "the question is logged first")
    reply = game.chat[-1]
    ok(reply[0] == "Sarah", "the questioned seat is the one that explains")
    ok(reply[1] == asker.name, "the explanation is addressed back to the asker")
    ok(len(reply[2]) > 80, "the answer is a real, reasoned explanation, not a one-liner")
    ok(len(game.chat) == 2, "a question draws exactly one explanation, no cascade")


def test_needle_stays_banter_not_a_lecture():
    game, players = talk_game(["Mike", "Sarah", "Emma"], seed=6)
    asker = players[0]
    game.deliver_chat(asker, "Sarah you got lucky there", in_action=True)
    for _name, _to, text in game.chat[1:]:
        ok(len(text) <= 140, "a plain needle gets short banter, not an explanation")


def test_model_chain_and_fallback():
    chain = ModelChain(["gpt-5.2", "gpt-5", "gpt-5.2", None])
    ok(chain.models == ["gpt-5.2", "gpt-5"], "duplicates and blanks dropped, order kept")
    ok(chain.current == "gpt-5.2", "starts at the preferred model")
    ok(chain.downgrade() and chain.current == "gpt-5", "downgrades to the next model")
    ok(not chain.downgrade(), "won't step past the last model")

    calls = []

    class FakeCompletions:
        @staticmethod
        def create(model=None, **kw):
            calls.append(model)
            if model == "gpt-5.2":
                raise RuntimeError("The model `gpt-5.2` does not exist or you lack access")

            class R:
                class C:
                    class M:
                        content = '{"action": "call", "say": ""}'
                    message = M
                choices = [C]
            return R

    class FakeClient:
        class chat:
            completions = FakeCompletions()

    ch = ModelChain(["gpt-5.2", "gpt-5"])
    brain = LLMBrain(FakeClient(), ch, PERSONALITIES[0], random.Random(0))
    out = brain._create([{"role": "user", "content": "x"}], json_mode=True)
    ok("gpt-5.2" in calls and "gpt-5" in calls, "tried the preferred model, then the fallback")
    ok(ch.current == "gpt-5", "the shared chain advanced to the working model")
    ok('"action"' in out, "a real completion came back from the fallback model")


# --------------------------------------------------------------- fuzz

def test_fuzz_full_games():
    for seed in range(30):
        rng = random.Random(seed)
        n = rng.choice([2, 3, 4, 5, 6])
        roster = rng.sample(PERSONALITIES, n)
        players = [LLMPlayer(pers["name"], 1000, pers, HeuristicBrain(pers, rng))
                   for pers in roster]
        game = TexasHoldemGame(players, rng=rng, interactive=False)
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


# --------------------------------------------------- softmax policy brain

def _seat(stack=1000, hole="As Ks"):
    p = Player("Hero", stack)
    p.hole = cards(hole)
    return p


def _pview(to_call=0, pot=100, can_raise=True, min_to=40, max_to=1000, board="", bb=20):
    return {
        "to_call": to_call, "pot": pot, "can_raise": can_raise,
        "min_raise_to": min_to, "max_raise_to": max_to,
        "board": cards(board) if board else [], "blinds": (bb // 2, bb),
    }


def _by_name(name):
    return next(p for p in PERSONALITIES if p["name"] == name)


def test_softmax_distribution():
    probs = _softmax([1.0, 0.0, -1.0], 1.0)
    ok(abs(sum(probs) - 1.0) < 1e-9, "softmax sums to 1")
    ok(probs[0] > probs[1] > probs[2], "softmax is monotone in score")
    hot = _softmax([2.0, 0.0], 2.0)
    cold = _softmax([2.0, 0.0], 0.2)
    ok(cold[0] > hot[0], "lower temperature concentrates weight on the top action")
    big = _softmax([1000.0, 1001.0], 1.0)
    ok(abs(sum(big) - 1.0) < 1e-9 and big[1] > big[0],
       "softmax stays numerically stable for large scores")


def test_policybrain_is_abstract():
    try:
        PolicyBrain(PERSONALITIES[0], random.Random(0))
        ok(False, "PolicyBrain should not be directly instantiable")
    except TypeError:
        ok(True, "PolicyBrain is abstract — construction is blocked")
    ok(PolicyBrain.__abstractmethods__ == frozenset({"_strength", "_action_utilities"}),
       "PolicyBrain declares _strength and _action_utilities abstract")

    class Half(PolicyBrain):  # implements only one extension point
        def _strength(self, hole, board):
            return 0.5
    try:
        Half(PERSONALITIES[0], random.Random(0))
        ok(False, "a subclass missing _action_utilities should stay abstract")
    except TypeError:
        ok(True, "a half-implemented subclass is still abstract")
    ok(not HeuristicBrain.__abstractmethods__,
       "HeuristicBrain implements both extension points — it is concrete")


def test_heuristic_actions_always_legal():
    rng = random.Random(12345)
    for _ in range(3000):
        brain = HeuristicBrain(rng.choice(PERSONALITIES), random.Random(rng.random()))
        stack = rng.randint(40, 2000)
        to_call = rng.choice([0, rng.randint(1, 20), rng.randint(20, stack)])
        room = stack > to_call                       # is there space above the call to raise into?
        can_raise = room and rng.random() < 0.85
        max_to = to_call + (rng.randint(1, stack - to_call) if room else 0)
        min_to = min(to_call + 20, max_to) if room else 0
        view = _pview(to_call=to_call, pot=rng.randint(1, 500), can_raise=can_raise,
                      min_to=min_to, max_to=max_to)
        seat = _seat(stack=stack)
        act, _ = brain.decide(seat, view)
        assert act.kind in (FOLD, CHECK, CALL, RAISE, ALL_IN), "illegal action kind %r" % act.kind
        assert not (to_call == 0 and act.kind == FOLD), "folded when checking was free"
        assert not (not can_raise and act.kind == RAISE), "raised when raising was illegal"
        if act.kind == RAISE:
            assert min_to <= act.amount <= max_to, ("raise %d outside window [%d, %d]"
                                                    % (act.amount, min_to, max_to))
    ok(True, "3000 random spots: HeuristicBrain always returns a legal, in-range action")


def _fold_count(brain, view, n=2000):
    folds = 0
    for i in range(n):
        brain.rng = random.Random(i)
        if brain.decide(_seat(), view)[0].kind == FOLD:
            folds += 1
    return folds


def test_dominated_action_pruned():
    shove = _pview(to_call=800, pot=200, can_raise=False, min_to=1000, max_to=1000)
    brain = HeuristicBrain(_by_name("Mike"), random.Random(0))  # loosest, stickiest seat

    brain._strength = lambda hole, board: 0.98  # the nuts
    ok(_fold_count(brain, shove) == 0,
       "never folds the nuts to a shove (dominated fold is pruned)")

    brain._strength = lambda hole, board: 0.30  # junk
    ok(_fold_count(brain, shove) > 1000,
       "usually folds junk facing a shove-sized bet")


def test_personality_differentiates():
    spot = _pview(to_call=100, pot=200, can_raise=True, min_to=200, max_to=1000)

    def raise_rate(name):
        brain = HeuristicBrain(_by_name(name), random.Random(0))
        brain._strength = lambda hole, board: 0.5  # same marginal hand for everyone
        hits = 0
        for i in range(2000):
            brain.rng = random.Random(i)
            if brain.decide(_seat(), spot)[0].kind in (RAISE, ALL_IN):
                hits += 1
        return hits

    mike = raise_rate("Mike")    # aggression 0.85, looseness 0.70
    sarah = raise_rate("Sarah")  # aggression 0.45, looseness 0.25
    emma = raise_rate("Emma")    # aggression 0.25 — a passive calling station
    ok(mike > sarah > emma,
       "on an identical hand, raise frequency tracks aggression: Mike > Sarah > Emma")


# --------------------------------------------------------------- odds

def test_odds_match_known_equities():
    """Pinned to published heads-up equities — if the simulator drifts, these
    move well outside sampling noise."""
    r = odds.hand_odds(cards("As Ah"), [], 1, random.Random(4), time_budget=0.5)
    ok(abs(r["equity"] - 0.853) < 0.02, "aces run ~85% against one random hand")
    r = odds.hand_odds(cards("As Ks"), [], 1, random.Random(5), time_budget=0.5)
    ok(abs(r["equity"] - 0.670) < 0.02, "suited AK runs ~67% against one random hand")
    r = odds.hand_odds(cards("7d 2c"), [], 1, random.Random(6), time_budget=0.5)
    ok(abs(r["equity"] - 0.346) < 0.02, "the worst hand in poker runs ~35%")
    r = odds.hand_odds(cards("As Ah"), [], 5, random.Random(7), time_budget=0.5)
    ok(abs(r["equity"] - 0.49) < 0.03, "aces drop to ~49% against five random hands")


def test_odds_decompose_into_categories():
    r = odds.hand_odds(cards("As Ks"), cards("Qs 7s 2h"), 2, random.Random(9),
                       time_budget=0.6)
    ok(abs(sum(c["make"] for c in r["categories"]) - 1.0) < 1e-9,
       "every runout lands in exactly one category")
    ok(abs(sum(c["win"] for c in r["categories"]) - r["equity"]) < 1e-9,
       "the per-category win column sums to total equity — that's the point of it")
    ok(abs(r["win"] + r["tie"] + r["lose"] - 1.0) < 1e-9,
       "win/tie/lose partition the runouts")
    ok(all(c["win"] <= c["make"] + 1e-9 for c in r["categories"]),
       "you can't win with a hand more often than you make it")

    # A flopped flush draw gets there 1 - (38/47)(37/46) = 35.0% of the time.
    made = sum(c["make"] for c in r["categories"]
               if c["cat"] in (evaluator.FLUSH, evaluator.STRAIGHT_FLUSH))
    ok(abs(made - 0.350) < 0.02, "a flopped flush draw completes ~35% by the river")


def test_odds_on_a_complete_board():
    r = odds.hand_odds(cards("As Ks"), cards("Qs 7s 2s Td 3h"), 1,
                       random.Random(2), time_budget=0.2)
    ok(r["final"] is True, "no cards to come — flagged as final")
    ok(len(r["categories"]) == 1, "hero's own category is already decided")
    ok(r["made"]["name"] == "a Flush, Ace high", "the made hand comes back named")
    ok(len(r["made"]["cards"]) == 5, "...with the five cards that play")
    ok(r["equity"] > 0.99, "the nut flush on a board nobody can beat is a lock")


def test_odds_declines_impossible_spots():
    ok(odds.hand_odds(cards("As"), [], 1, random.Random(1)) is None,
       "a single hole card isn't a hand to price")
    ok(odds.hand_odds(cards("As Ks"), cards("Qs 7s 2h"), 30, random.Random(1)) is None,
       "more opponents than the deck can deal for -> no answer, not a crash")


# --------------------------------------------------------------- autopilot

def test_autopilot_fold_waits_for_a_bet():
    hero = HumanPlayer("You", 1000)
    hero.arm_auto(AUTO_FOLD, "FLOP")
    ok(hero.auto_action({"street": "FLOP", "to_call": 0}).kind == CHECK,
       "pre-fold takes the free card instead of folding for nothing")
    ok(hero.auto_action({"street": "FLOP", "to_call": 50}).kind == FOLD,
       "pre-fold folds the moment it actually costs something")
    ok(hero.auto == AUTO_FOLD, "and stays armed across streets")


def test_autopilot_call_modes():
    hero = HumanPlayer("You", 1000)
    hero.arm_auto(AUTO_CALL, "PREFLOP")
    ok(hero.auto_action({"street": "RIVER", "to_call": 900}).kind == CALL,
       "call-everything calls any amount, any street")
    ok(hero.auto_action({"street": "RIVER", "to_call": 0}).kind == CHECK,
       "...and checks when there's nothing to call")

    hero.arm_auto(AUTO_CALL_STREET, "FLOP")
    ok(hero.auto_action({"street": "FLOP", "to_call": 80}).kind == CALL,
       "call-this-street calls on the street it was armed for")
    ok(hero.auto_action({"street": "TURN", "to_call": 80}) is None,
       "...and hands the controls back when that street ends")
    ok(hero.auto is None, "expiring disarms it rather than leaving it half-on")


def test_autopilot_answers_without_prompting():
    # ui.QUIET makes safe_input raise, and show_table would blow up on this
    # stub view — so reaching the prompt at all fails the test loudly.
    hero = HumanPlayer("You", 1000)
    hero.arm_auto(AUTO_CALL, "FLOP")
    action, say = hero.decide({"street": "FLOP", "to_call": 60})
    ok(action.kind == CALL and say is None,
       "an armed seat answers the engine without ever asking the human")


def test_autopilot_is_per_hand_and_validated():
    hero = HumanPlayer("You", 1000)
    hero.arm_auto(AUTO_CALL, "FLOP")
    hero.reset_for_hand()
    ok(hero.auto is None, "a commitment only covers the hand it was made in")
    hero.arm_auto("wire the pot to me")
    ok(hero.auto is None, "an unknown mode is refused, not armed")
    hero.arm_auto(AUTO_FOLD, "FLOP")
    hero.arm_auto(None)
    ok(hero.auto is None, "and it can be handed back")
    ok(hero.auto_action({"street": "FLOP", "to_call": 999}) is None,
       "a disarmed seat is asked like anyone else")


# --------------------------------------------------------------- hand result

class RecordingSink(ui.Sink):
    def __init__(self):
        self.results = []
        self.odds = []
        self.autos = []

    def hand_result(self, hand_no, rows, board):
        self.results.append({"hand_no": hand_no, "rows": rows, "board": board})

    def hero_odds(self, payload):
        self.odds.append(payload)

    def autopilot(self, player, mode):
        self.autos.append((player.name, mode))


def result_game(reveal_all=False):
    """A hand frozen at the end: hero holds aces, A folded, B showed down."""
    hero = HumanPlayer("You", 1000)
    a, b = Player("A", 1000), Player("B", 1000)
    game = make_game([hero, a, b], reveal_all=reveal_all)
    game.hand_players = [hero, a, b]
    game.hand_no = 3
    game.board = cards("2h 5c 7s 9d Jc")
    hero.hole, a.hole, b.hole = cards("As Ad"), cards("Ks Kd"), cards("Qs Qd")
    a.folded = True
    game.shown = {"B"}                 # B's cards went face up at showdown
    game.hand_winnings = {"B": 300}
    sink = RecordingSink()
    ui.set_sink(sink)
    try:
        game.show_hand_result()
    finally:
        ui.set_sink(None)
    return sink.results[0]


def test_hand_result_ranks_every_seat_by_strength():
    res = result_game()
    rows = res["rows"]
    ok(res["hand_no"] == 3 and len(res["board"]) == 5, "the finished board comes with it")
    ok(len(rows) == 3, "every seat that was dealt in gets a row, folded or not")
    ok([r["player"].name for r in rows] == ["You", "B", "A"],
       "strongest hand first, and anything mucked sinks to the bottom")
    ok(rows[0]["hand"] == "a Pair of Aces", "the formula each seat arrived at")
    ok(len(rows[0]["best5"]) == 5, "and the exact five cards that played")
    ok(rows[0]["rank"] > rows[1]["rank"], "rows are ordered by real hand rank")
    ok(rows[1]["won"] == 300 and rows[0]["won"] == 0, "chips collected are booked per seat")


def test_hand_result_keeps_mucked_cards_secret():
    rows = result_game()["rows"]
    folded = next(r for r in rows if r["player"].name == "A")
    ok(not folded["known"], "a seat that folded without showing stays hidden")
    ok(folded["hole"] == [] and folded["best5"] is None and folded["hand"] is None,
       "nothing about a mucked hand leaks into the panel")
    ok(folded["folded"], "though the panel still shows they were in the hand")

    peeked = next(r for r in result_game(reveal_all=True)["rows"]
                  if r["player"].name == "A")
    ok(peeked["known"] and peeked["hand"] == "a Pair of Kings",
       "peek mode is what opens folded hands up")
    ok(peeked["folded"], "a peeked hand is still marked as folded")


def test_hand_result_survives_a_preflop_fold_around():
    hero = HumanPlayer("You", 1000)
    other = Player("A", 1000)
    game = make_game([hero, other])
    game.hand_players = [hero, other]
    game.hand_no = 1
    game.board = []                    # nobody saw a flop
    hero.hole, other.hole = cards("As Ad"), cards("Ks Kd")
    game.hand_winnings = {"You": 30}
    sink = RecordingSink()
    ui.set_sink(sink)
    try:
        game.show_hand_result()
    finally:
        ui.set_sink(None)
    rows = sink.results[0]["rows"]
    hero_row = next(r for r in rows if r["player"].is_human)
    ok(hero_row["known"] and hero_row["hole"], "you always get to see your own cards")
    ok(hero_row["hand"] is None and hero_row["best5"] is None,
       "with no board there's no five-card hand to name — and no crash")


def test_hero_odds_only_run_for_a_live_human():
    hero = HumanPlayer("You", 1000)
    a, b = Player("A", 1000), Player("B", 1000)
    game = make_game([hero, a, b])
    game.hand_players = [hero, a, b]
    game.board = cards("2h 5c 7s")
    hero.hole, a.hole, b.hole = cards("As Ad"), cards("Ks Kd"), cards("Qs Qd")

    sink = RecordingSink()
    ui.set_sink(sink)
    try:
        game.update_hero_odds()
        ok(len(sink.odds) == 1, "the human gets a read on their spot")
        ok(abs(sink.odds[0]["equity"] - 1.0) < 0.5, "...and it's a real number")
        ok(sink.odds[0]["opponents"] == 2, "priced against the seats still in the hand")

        game.update_hero_odds()
        ok(len(sink.odds) == 1, "nothing has moved — the same read isn't sent twice")

        a.folded = True
        game.update_hero_odds()
        ok(len(sink.odds) == 2 and sink.odds[1]["opponents"] == 1,
           "a fold changes what you're up against, so the read is refreshed")

        hero.folded = True
        game.update_hero_odds()
        ok(len(sink.odds) == 2, "a folded human isn't handed odds on a dead hand")
    finally:
        ui.set_sink(None)

    # Switched off, nothing is computed at all.
    quiet = make_game([hero, a, b], show_odds=False)
    quiet.hand_players = [hero, a, b]
    quiet.board = cards("2h 5c 7s")
    hero.folded = False
    sink2 = RecordingSink()
    ui.set_sink(sink2)
    try:
        quiet.update_hero_odds()
    finally:
        ui.set_sink(None)
    ok(not sink2.odds, "--no-odds means the simulator never runs")


def test_hand_winnings_track_every_payout():
    players = [Player("P0", 0), Player("P1", 0), Player("P2", 0)]
    game = make_game(players)
    game.hand_players = players
    game.board = cards("2h 5c 7s 9d Jc")
    for pl, hole, committed in zip(players, ["As Ad", "Ks Kd", ""], [100, 100, 40]):
        pl.hole = cards(hole) if hole else []
        pl.committed = committed
    players[2].folded = True
    contenders = [pl for pl in players if not pl.folded]
    results = {pl: evaluator.best_hand(pl.hole + game.board) for pl in contenders}
    game.award_pots(contenders, results)
    ok(game.hand_winnings == {"P0": 240}, "the winner's collection is booked, and only theirs")
    ok(players[0].stack == 240, "and it matches the chips actually paid out")

    # Odd chips are booked to whoever they were paid to, not rounded away.
    split = [Player("A", 0), Player("B", 0)]
    game2 = make_game(split)
    game2.hand_players = split
    game2.board = cards("2h 5c 7s 9d Kh")
    for pl, hole in zip(split, ["Ah Kd", "As Kc"]):
        pl.hole = cards(hole)
        pl.committed = 101
    res2 = {pl: evaluator.best_hand(pl.hole + game2.board) for pl in split}
    game2.award_pots(split, res2)
    ok(sum(game2.hand_winnings.values()) == 202, "a split pot is booked in full")
    ok(game2.hand_winnings["A"] == split[0].stack
       and game2.hand_winnings["B"] == split[1].stack,
       "each seat's booked total matches its own stack")


if __name__ == "__main__":
    test_evaluator()
    test_fast_ranker_agrees_with_brute_force()
    test_fold_around()
    test_raise_call_and_min_raise()
    test_min_raise_clamping()
    test_all_in_showdown_conserves_chips()
    test_side_pots()
    test_uncalled_chips_returned()
    test_split_pot_with_odd_chip()
    test_llm_parsing()
    test_spoken_action_detection()
    test_words_conform_to_moves()
    test_deck_integrity()
    test_deal_fairness()
    test_system_random_games()
    test_rebuy_adds_debt_nobody_leaves()
    test_buy_chips_keeps_net_worth()
    test_buy_decision_capped_and_reloads_short_stacks()
    test_llm_buy_decision_parses_and_clamps()
    test_ai_buy_ins_preserve_chip_invariant()
    test_addressee_resolution()
    test_table_talk_gets_replies()
    test_move_reactions()
    test_agents_answer_each_other()
    test_move_question_detection()
    test_questioning_a_move_gets_a_reasoned_answer()
    test_needle_stays_banter_not_a_lecture()
    test_model_chain_and_fallback()
    test_fuzz_full_games()
    test_softmax_distribution()
    test_policybrain_is_abstract()
    test_heuristic_actions_always_legal()
    test_dominated_action_pruned()
    test_personality_differentiates()
    test_odds_match_known_equities()
    test_odds_decompose_into_categories()
    test_odds_on_a_complete_board()
    test_odds_declines_impossible_spots()
    test_autopilot_fold_waits_for_a_bet()
    test_autopilot_call_modes()
    test_autopilot_answers_without_prompting()
    test_autopilot_is_per_hand_and_validated()
    test_hand_result_ranks_every_seat_by_strength()
    test_hand_result_keeps_mucked_cards_secret()
    test_hand_result_survives_a_preflop_fold_around()
    test_hero_odds_only_run_for_a_live_human()
    test_hand_winnings_track_every_payout()
    print("all good: %d checks passed" % CHECKS["passed"])
