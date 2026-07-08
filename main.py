"""Texas Hold'em vs the machines — entry point.

You sit at a table full of OpenAI-powered opponents, each with its own
personality, who react to the board, the stacks, the betting, and whatever
you type at them with `say <text>`.
"""

import argparse
import os
import random
import sys

from holdem import ui
from holdem.brains import PERSONALITIES, HeuristicBrain, LLMBrain, ModelChain
from holdem.game import TexasHoldemGame
from holdem.players import HumanPlayer, LLMPlayer
from holdem.ui import QuitGame

# Preferred model first; the rest are automatic fallbacks if the account
# can't reach it, so a wrong/unavailable id never breaks the whole table.
DEFAULT_MODEL = "gpt-5.2"
FALLBACK_MODELS = ["gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-4o-mini"]


def load_dotenv():
    """Tiny .env loader (KEY=value lines) so no extra dependency is needed."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def parse_args():
    parser = argparse.ArgumentParser(description="No-Limit Texas Hold'em vs LLM agents")
    parser.add_argument("--opponents", type=int, default=5, metavar="N",
                        help="number of AI opponents, 1-7 (default 5)")
    parser.add_argument("--stack", type=int, default=1000, help="starting stack (default 1000)")
    parser.add_argument("--sb", type=int, default=10, help="small blind (default 10)")
    parser.add_argument("--bb", type=int, default=20, help="big blind (default 20)")
    parser.add_argument("--model", default=None,
                        help="preferred OpenAI model (default: $OPENAI_MODEL or %s; "
                             "auto-falls back if unavailable)" % DEFAULT_MODEL)
    parser.add_argument("--offline", action="store_true",
                        help="play without the OpenAI API (built-in bot logic)")
    parser.add_argument("--show-cards", action="store_true",
                        help="peek mode: reveal every opponent's hole cards after "
                             "each hand ends (spoiler — for study/debugging)")
    parser.add_argument("--seed", type=int, default=None, help="random seed (for reproducible decks)")
    return parser.parse_args()


def main():
    ui.enable_colors()
    try:
        if sys.stdout.isatty():
            sys.stdout.reconfigure(errors="replace")
        else:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    args = parse_args()
    load_dotenv()
    if args.seed is not None:
        rng = random.Random(args.seed)  # reproducible decks, for testing only
    else:
        # Cryptographically secure OS entropy: shuffles are unpredictable and
        # unbiasable — no seat is favored, and nobody (AI included) can know
        # or influence what's coming.
        rng = random.SystemRandom()

    ui.title_screen()

    client = None
    chosen = args.model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    model_chain = ModelChain([chosen] + FALLBACK_MODELS)
    if args.offline:
        print(ui.dim(" offline mode: opponents run on built-in instincts, no API calls.\n"))
    elif not os.environ.get("OPENAI_API_KEY"):
        print(ui.dim(" No OPENAI_API_KEY found (set the env var or put it in a .env file)."))
        print(ui.dim(" Falling back to offline mode — built-in bot logic, no API calls.\n"))
        args.offline = True
    else:
        from openai import OpenAI
        client = OpenAI(timeout=45.0, max_retries=2)
        print(ui.dim(" opponents powered by OpenAI model: %s (auto-fallback if unavailable)\n"
                     % chosen))

    try:
        name = ui.safe_input(" What's your name, champ? [You] ").strip() or "You"
    except QuitGame:
        return

    count = max(1, min(args.opponents, len(PERSONALITIES)))
    roster = rng.sample(PERSONALITIES, count)
    players = [HumanPlayer(name[:14], args.stack)]
    for personality in roster:
        if args.offline:
            brain = HeuristicBrain(personality, rng)
        else:
            brain = LLMBrain(client, model_chain, personality, rng)
        players.append(LLMPlayer(personality["name"], args.stack, personality, brain))

    print(" Tonight's table: " + ", ".join(ui.name_str(p) for p in players[1:]))
    if args.seed is not None:
        print(ui.dim(" deck: seeded shuffle (reproducible) — seed %d" % args.seed))
    else:
        print(ui.dim(" deck: cryptographically random shuffle (OS entropy)"))
    if args.show_cards:
        print(ui.dim(" peek mode: everyone's hole cards are revealed after each hand."))
    print(ui.dim(" Type 'h' on your turn for the commands. Good luck.\n"))

    game = TexasHoldemGame(players, sb=args.sb, bb=args.bb, rng=rng,
                           reveal_all=args.show_cards)
    try:
        game.run()
    except (QuitGame, KeyboardInterrupt):
        ui.show_standings(game.players, "chip counts when you left")
    print("\n Thanks for playing!\n")


if __name__ == "__main__":
    main()
