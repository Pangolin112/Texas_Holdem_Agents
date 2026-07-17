"""The HTTP + SSE server: routes browser requests to a Session, streams game
events back, and serves the static 2D-table front-end."""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from holdem import ui
from holdem.players import AUTO_ADVISOR, AUTO_FOLD, AUTOPILOT_MODES

from .session import SESSIONS, SESSIONS_LOCK, start_session
from .util import STATIC_DIR, load_dotenv, server_config

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
