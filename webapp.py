"""Texas Hold'em vs the machines — web version.

Same game, same brains, same rules as the terminal (`main.py`): this file adds
a browser front-end with a 2D table instead of a text one. It does NOT
reimplement any poker logic. The real, shared engine (`holdem.game`,
`holdem.brains`, `holdem.evaluator`, ...) runs unchanged in a background thread;
a `WebSink` installed on that thread (see `holdem.ui.set_sink`) turns every game
event into a JSON message streamed to the browser over Server-Sent Events, and
feeds the player's clicks back in as the very same command strings the terminal
accepts ("f", "c", "r 120", "a", "say ...", "buy 200", "q").

Because both front-ends drive one engine, any new game feature added to the
engine shows up in the terminal and the web version at once — the guiding rule
for this project.

Run:  python webapp.py            (then open http://127.0.0.1:8000)
      python webapp.py --port 8080 --no-browser
"""

import argparse
import json
import os
import queue
import random
import re
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from holdem import ui
from holdem.advisor import ADVISOR, HeuristicAdvisor, LLMAdvisor
from holdem.brains import PERSONALITIES, HeuristicBrain, LLMBrain, build_model_chain
from holdem.cards import RED_SUITS, SUIT_SYMBOLS, VALUE_CHARS, VALUE_LABELS
from holdem.game import TexasHoldemGame
from holdem.players import (AUTO_ADVISOR, AUTO_FOLD, AUTOPILOT_MODES,
                            HumanPlayer, LLMPlayer)
from holdem.ui import QuitGame
from holdem import evaluator

# Same model defaults as the terminal entry point.
DEFAULT_MODEL = "gpt-5.2"
FALLBACK_MODELS = ["gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-4o-mini"]
OPENAI_MODEL_SUGGESTIONS = list(FALLBACK_MODELS)
DEEPSEEK_MODEL_SUGGESTIONS = ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"]

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

_QUIT = object()  # sentinel pushed onto the input queue to end a blocked wait


# --------------------------------------------------------------------------- #
# .env loader (identical to main.py — kept dependency-free)
# --------------------------------------------------------------------------- #

def load_dotenv():
    path = os.path.join(HERE, ".env")
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


def server_config():
    """Defaults the setup screen should show (from .env / host env)."""
    chosen = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    base_url = os.environ.get("OPENAI_BASE_URL")
    on_deepseek = bool(base_url and "deepseek" in base_url) or chosen.startswith("deepseek")
    provider = "DeepSeek" if on_deepseek else "OpenAI"
    return {
        "model": chosen,
        "provider": provider,
        "has_api_key": bool(os.environ.get("OPENAI_API_KEY")),
        "model_suggestions": (DEEPSEEK_MODEL_SUGGESTIONS if on_deepseek
                              else OPENAI_MODEL_SUGGESTIONS),
    }


# --------------------------------------------------------------------------- #
# Serialization: engine objects -> JSON-safe dicts for the browser
# --------------------------------------------------------------------------- #

def card_data(card):
    """A card the browser can draw: display rank, suit glyph, color, code."""
    return {
        "rank": VALUE_LABELS[card.value],       # "10", "K", "A"
        "suit": card.suit,                       # s h d c
        "symbol": SUIT_SYMBOLS[card.suit],       # the pip
        "red": card.suit in RED_SUITS,
        "code": VALUE_CHARS[card.value] + card.suit,
    }


def cards_data(cards):
    return [card_data(c) for c in cards]


# --------------------------------------------------------------------------- #
# Session: one running game + its two message queues
# --------------------------------------------------------------------------- #

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


SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# WebSink: the presenter the engine talks to on the game thread
# --------------------------------------------------------------------------- #

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


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text):
    return _ANSI.sub("", str(text))


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


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "HoldemWeb/1.0"

    def log_message(self, *args):
        pass  # keep the console quiet

    # -- helpers ------------------------------------------------------------

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _session(self, query):
        sid = (query.get("sid") or [None])[0]
        return SESSIONS.get(sid)

    # -- routing ------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/" or path == "/index.html":
            return self._serve_static("index.html")
        if path in ("/healthz", "/api/health"):
            return self._json({"ok": True, "games": len(SESSIONS)})
        if path == "/api/config":
            return self._json(server_config())
        if path == "/api/events":
            return self._events(query)
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/new":
            options = self._read_json()
            # Optional shared gate: if the host sets ACCESS_CODE, a game only
            # starts when the browser sends the matching code. Leave it unset to
            # keep the table open to anyone with the link.
            code = os.environ.get("ACCESS_CODE", "")
            if code and str(options.get("access_code", "")) != code:
                return self._json({"ok": False, "error": "access code required"},
                                  status=403)
            session = start_session(options)
            return self._json({"sid": session.sid})
        if path == "/api/input":
            session = self._session(query)
            if session is None or not session.alive:
                return self._json({"ok": False, "error": "no active game"}, status=409)
            body = self._read_json()
            line = body.get("line", "")
            session.inbound.put(line)
            return self._json({"ok": True})
        if path == "/api/say":
            # Out-of-band table talk: works at ANY moment of the game, not just
            # when the engine is waiting for the human's input.
            session = self._session(query)
            if session is None or not session.alive:
                return self._json({"ok": False, "error": "no active game"}, status=409)
            text = str(self._read_json().get("text", "")).strip()[:200]
            if text:
                session.chat_queue.put(text)
            return self._json({"ok": True})
        if path == "/api/auto":
            # Autopilot is armed OUT-OF-BAND, like /api/say: "fold in advance"
            # only means anything if you can click it while someone else is
            # still thinking, and the input queue is read only on your turn.
            session = self._session(query)
            if session is None or not session.alive:
                return self._json({"ok": False, "error": "no active game"}, status=409)
            return self._json(self._arm_auto(session, self._read_json().get("mode")))
        if path == "/api/tts":
            return self._tts(query)
        if path == "/api/quit":
            session = self._session(query)
            if session is not None:
                # The send-off goes into the stream BEFORE stop() enqueues
                # "closed", so the browser shows the coach's last word and only
                # then learns the table is gone. Computed here on the HTTP
                # thread — the game thread may be blocked mid-decision, and
                # leaving shouldn't wait on an opponent's think.
                if session.alive and session.game is not None and session.sink is not None:
                    ui.set_sink(session.sink)
                    try:
                        session.game.farewell()
                    except Exception:
                        pass  # a failed goodbye must never block the exit
                    finally:
                        ui.set_sink(None)
                session.stop()
            return self._json({"ok": True})
        self.send_error(404)

    # -- autopilot: a move committed to before the turn arrives -------------

    def _arm_auto(self, session, mode):
        """Arm (or clear, with mode=None) the human's autopilot.

        Two cases. Usually it isn't the human's turn: we set the flag and the
        engine fires it the moment the turn lands. But if the engine is ALREADY
        blocked waiting on them, `decide` has passed its autopilot check for
        this turn — so setting the flag alone would leave the table hanging on
        a player who thinks they've answered. In that case we also push the
        matching command to settle the move now; the flag still governs the
        rest of the hand.
        """
        game = session.game
        human = game.human if game is not None else None
        if human is None or not hasattr(human, "arm_auto"):
            return {"ok": False, "error": "no human seat"}
        if mode not in AUTOPILOT_MODES:
            mode = None
        advice = game.hero_advice
        if mode == AUTO_ADVISOR and not advice:
            # Nothing to follow — don't arm a mode that would just hand the
            # controls straight back.
            return {"ok": False, "error": "no advice yet"}
        # arm_auto reports through the sink, which is thread-local — this is an
        # HTTP thread, so lend it the session's sink for the call.
        ui.set_sink(session.sink)
        try:
            human.arm_auto(mode, game.street)
        finally:
            ui.set_sink(None)
        pending = session.pending_await
        if mode and pending is not None and pending.get("mode") == "action":
            if mode == AUTO_ADVISOR:
                line = advice.get("command") or "c"
            elif mode == AUTO_FOLD and ((pending.get("legal") or {}).get("to_call") or 0) > 0:
                line = "f"
            else:
                line = "c"
            session.inbound.put(line)
        return {"ok": True, "mode": mode}

    # -- natural agent voices (OpenAI TTS, proxied so the key stays here) ----

    def _tts(self, query):
        session = self._session(query)
        if session is None or session.tts_client is None:
            return self._json({"ok": False, "error": "tts unavailable"}, status=404)
        body = self._read_json()
        text = str(body.get("text", "")).strip()[:500]
        name = str(body.get("name", ""))
        if not text:
            return self._json({"ok": False, "error": "no text"}, status=400)
        voice, style = session.voices.get(name, ("alloy", ""))
        model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        kwargs = {"model": model, "voice": voice, "input": text,
                  "response_format": "mp3"}
        # Style steering exists only on the gpt-4o-mini-tts family.
        if style and model.startswith("gpt-4o-mini-tts"):
            kwargs["instructions"] = style
        try:
            resp = session.tts_client.audio.speech.create(**kwargs)
            audio = getattr(resp, "content", None) or resp.read()
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)[:200]}, status=502)
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(audio)

    # -- static files -------------------------------------------------------

    def _serve_static(self, rel):
        rel = rel.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404)
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = STATIC_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # -- Server-Sent Events stream -----------------------------------------

    def _events(self, query):
        session = self._session(query)
        if session is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def write(event):
            payload = "data: %s\n\n" % json.dumps(event)
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()

        try:
            # Catch a (re)connecting tab up to the current state immediately.
            if session.last_state is not None:
                write({"type": "sync", "state": session.last_state})
            if session.last_odds is not None:
                # Without its stale snapshot — the sync above is the newer one.
                write({"type": "odds", "odds": session.last_odds["odds"]})
            if session.pending_await is not None:
                write(session.pending_await)
            while session.alive or not session.outbound.empty():
                try:
                    event = session.outbound.get(timeout=15)
                except queue.Empty:
                    write({"type": "ping"})  # keep the connection warm
                    continue
                write(event)
                if event.get("type") in ("game_over", "closed"):
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # browser tab closed — the game thread keeps its state


def main():
    parser = argparse.ArgumentParser(description="Texas Hold'em — web version")
    # A cloud host (Render, Hugging Face Spaces, Fly, ...) injects the port to
    # bind on as $PORT and expects the server on all interfaces; honor that so
    # the same file runs locally (127.0.0.1:8000) and deployed with no flags.
    hosted = bool(os.environ.get("PORT"))
    parser.add_argument("--host", default="0.0.0.0" if hosted else "127.0.0.1")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--no-browser", action="store_true",
                        help="don't auto-open a browser tab")
    args = parser.parse_args()

    load_dotenv()
    ui.enable_colors()
    # Legacy Windows consoles are often GBK — keep our own prints from crashing
    # on the suit glyphs / dashes (the browser handles Unicode fine regardless).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d" % (args.host if args.host != "0.0.0.0" else "127.0.0.1",
                            args.port)
    print("  Texas Hold'em -- web table  (spades hearts diamonds clubs)")
    print("  serving at %s   (Ctrl-C to stop)" % url)
    if not os.environ.get("OPENAI_API_KEY"):
        print("  note: no OPENAI_API_KEY set -- the web setup screen can still")
        print("        start a game in offline mode (built-in bot logic).")
    if not args.no_browser and not hosted:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  shutting down.")
    finally:
        with SESSIONS_LOCK:
            for s in SESSIONS.values():
                s.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
