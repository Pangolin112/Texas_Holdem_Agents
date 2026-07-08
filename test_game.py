"""Self-contained test suite (stdlib only): python test_game.py"""

import random

from holdem import evaluator, ui
from holdem.brains import (PERSONALITIES, HeuristicBrain, LLMBrain, ModelChain,
                           spoken_action)
from holdem.cards import Card, Deck, RANK_VALUES
from holdem.game import TexasHoldemGame, looks_like_move_question
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
    test_spoken_action_detection()
    test_words_conform_to_moves()
    test_deck_integrity()
    test_deal_fairness()
    test_system_random_games()
    test_rebuy_adds_debt_nobody_leaves()
    test_buy_chips_keeps_net_worth()
    test_buy_decision_capped_and_reloads_short_stacks()
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
    print("all good: %d checks passed" % CHECKS["passed"])
