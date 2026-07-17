"""One running game: the Session (its queues and reconnect state), building the
game from setup options, and the threads that drive it."""

from __future__ import annotations

import os
import queue
import random
import threading
import uuid

from holdem import ui
from holdem.advisor import ADVISOR, HeuristicAdvisor, LLMAdvisor
from holdem.brains import PERSONALITIES, HeuristicBrain, LLMBrain, build_model_chain
from holdem.game import TexasHoldemGame
from holdem.players import HumanPlayer, LLMPlayer
from holdem.ui import QuitGame

from .sink import WebSink
from .util import DEFAULT_MODEL, FALLBACK_MODELS, _QUIT

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


class Session:
    def __init__(self, sid, options):
        self.sid = sid
        self.options = options
        self.outbound = queue.Queue()   # engine -> browser (events)
        self.inbound = queue.Queue()    # browser -> engine (command lines)
        self.chat_queue = queue.Queue() # browser -> table talk, ANY time
        self.alive = True
        self.last_state = None          # newest full table snapshot (for reconnects)
        self.last_odds = None           # newest odds event (ditto — see emit)
        self.pending_await = None       # the current input request, if blocked
        self.sink = None
        self.thread = None
        self.game = None
        self.tts_client = None          # OpenAI client for /api/tts (None offline)
        self.voices = {}                # seat name -> (tts voice, style hint)

    def emit(self, event):
        if event.get("state") is not None:
            self.last_state = event["state"]
        # Odds are sent once per spot, not folded into every snapshot, so a tab
        # that reconnects mid-hand would sit with an empty panel until the next
        # street. Keep the last one to replay, and drop it when the deal changes.
        kind = event.get("type")
        if kind == "odds":
            self.last_odds = event
        elif kind == "hand_start":
            self.last_odds = None
        self.outbound.put(event)

    def stop(self):
        if not self.alive:
            return
        self.alive = False
        self.inbound.put(_QUIT)         # release any blocked input()
        self.chat_queue.put(_QUIT)      # ...and the chat worker
        self.outbound.put({"type": "closed"})


# --------------------------------------------------------------------------- #
# Building the game from the setup options (mirrors main.py)
# --------------------------------------------------------------------------- #

def build_game(options):
    seed = options.get("seed")
    if seed is not None:
        rng = random.Random(int(seed))
    else:
        rng = random.SystemRandom()

    offline = bool(options.get("offline"))
    chosen = (options.get("model") or os.environ.get("OPENAI_MODEL")
              or DEFAULT_MODEL)
    base_url = os.environ.get("OPENAI_BASE_URL")
    on_deepseek = bool(base_url and "deepseek" in base_url) or chosen.startswith("deepseek")
    provider = "DeepSeek" if on_deepseek else "OpenAI"
    model_chain = build_model_chain(chosen, base_url, FALLBACK_MODELS)

    client = None
    note = None
    if offline:
        note = "Offline mode: opponents run on built-in instincts, no API calls."
    elif not os.environ.get("OPENAI_API_KEY"):
        offline = True
        note = ("No OPENAI_API_KEY found — falling back to offline mode "
                "(built-in bot logic, no API calls).")
    else:
        from openai import OpenAI
        client = OpenAI(timeout=45.0, max_retries=2)
        note = "Opponents powered by %s model: %s (auto-fallback if unavailable)." % (provider, chosen)

    name = (options.get("name") or "You").strip()[:14] or "You"
    stack = int(options.get("stack") or 1000)
    sb = int(options.get("sb") or 10)
    bb = int(options.get("bb") or 20)
    count = max(1, min(int(options.get("opponents") or 5), len(PERSONALITIES)))
    reveal_all = bool(options.get("show_cards"))
    show_odds = options.get("odds", True) is not False
    # The coach reasons from the equity numbers, so it can't run without them.
    want_coach = options.get("coach", True) is not False and show_odds
    fast_forward = options.get("fast", True) is not False
    # Table language: what the agents speak ("zh" = Chinese, default English).
    lang = "zh" if str(options.get("language") or "").lower().startswith("zh") else "en"

    roster = rng.sample(PERSONALITIES, count)
    players = [HumanPlayer(name, stack)]
    for personality in roster:
        if offline:
            brain = HeuristicBrain(personality, rng, lang=lang)
        else:
            brain = LLMBrain(client, model_chain, personality, rng, lang=lang)
        players.append(LLMPlayer(personality["name"], stack, personality, brain))

    coach = None
    if want_coach:
        coach = (HeuristicAdvisor(rng, lang=lang) if offline
                 else LLMAdvisor(client, model_chain, rng, lang=lang))

    game = TexasHoldemGame(players, sb=sb, bb=bb, rng=rng, reveal_all=reveal_all,
                           language=lang, show_odds=show_odds, advisor=coach,
                           fast_forward=fast_forward)
    meta = {
        "note": note,
        "offline": offline,
        "model": None if offline else chosen,
        "provider": provider,
        "seed": seed,
        "show_cards": reveal_all,
        "odds": show_odds,
        "coach": coach is not None,
        "coach_name": ADVISOR["name"],
        "fast": fast_forward,
        "language": lang,
        # natural agent voices need the API; the browser falls back to its own
        # speech synthesis when this is False. DeepSeek's endpoint has no TTS,
        # so voices fall back there too.
        "tts": client is not None and not on_deepseek,
        "roster": [p.name for p in players[1:]],
        "hero": name,
    }
    # The web layer only reuses the returned client for TTS, which DeepSeek
    # doesn't provide — hand back None there so voices degrade gracefully.
    return game, meta, (client if not on_deepseek else None)


def chat_worker(session, game, sink):
    """Session thread that delivers the human's chat OUT-OF-BAND.

    The game thread spends most of its life blocked — inside an opponent's
    (possibly slow) LLM decision or waiting for the human's move. Lines sent
    to /api/say land here instead of the input queue, so the table hears the
    human the moment they speak and answers (selectively, via the engine's own
    one-reply logic) even while a seat is still thinking. The engine's
    talk_lock keeps concurrent chat consistent."""
    ui.set_sink(sink)  # the sink is thread-local: this thread reports too
    while session.alive:
        try:
            text = session.chat_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if text is _QUIT:
            break
        try:
            if game.human is not None:
                game.table_talk(game.human, text)
        except QuitGame:
            break
        except Exception as exc:  # a failed reply must never kill the table
            session.outbound.put({"type": "log", "level": "warn",
                                  "text": "chat hiccup (%s): %s"
                                          % (type(exc).__name__, str(exc)[:120])})
    ui.set_sink(None)


def run_game(session):
    """Game-thread target: install the sink, then run the shared engine."""
    try:
        game, meta, client = build_game(session.options)
    except Exception as exc:  # setup failure -> tell the browser, don't crash
        session.outbound.put({"type": "fatal", "text": "Could not start game: %s" % exc})
        session.alive = False
        return

    sink = WebSink(session, game)
    session.sink = sink
    session.game = game
    session.tts_client = client
    session.voices = {
        p.name: (p.personality.get("voice", "alloy"),
                 p.personality.get("tts_style", ""))
        for p in game.players if hasattr(p, "personality")
    }
    # The coach isn't a seat, but it talks — give it its own voice.
    session.voices[ADVISOR["name"]] = (ADVISOR["voice"], ADVISOR["tts_style"])
    ui.set_sink(sink)
    talker = threading.Thread(target=chat_worker, args=(session, game, sink),
                              daemon=True)
    talker.start()
    session.outbound.put({"type": "start", "meta": meta, "state": sink.snapshot()})
    try:
        game.run()
    except QuitGame:
        pass
    except Exception as exc:
        session.outbound.put({"type": "log", "level": "error",
                              "text": "engine error (%s): %s"
                                      % (type(exc).__name__, exc)})
    finally:
        session.outbound.put({"type": "game_over", "state": sink.snapshot()})
        session.alive = False
        session.chat_queue.put(_QUIT)
        ui.set_sink(None)


def start_session(options):
    with SESSIONS_LOCK:
        # A public link means several people may be at their own tables at once,
        # so we keep one session per browser (keyed by sid) instead of the old
        # single-game behavior. Reap finished games, and cap how many run at
        # once (MAX_GAMES) so one instance — and the API bill — stays bounded;
        # over the cap, the oldest table is retired first.
        for dead in [s for s, sess in SESSIONS.items() if not sess.alive]:
            SESSIONS.pop(dead, None)
        max_games = max(1, int(os.environ.get("MAX_GAMES", "12")))
        while len(SESSIONS) >= max_games:
            old_sid, old = next(iter(SESSIONS.items()))
            old.stop()
            SESSIONS.pop(old_sid, None)
        sid = uuid.uuid4().hex
        session = Session(sid, options)
        SESSIONS[sid] = session
    thread = threading.Thread(target=run_game, args=(session,), daemon=True)
    session.thread = thread
    thread.start()
    return session
