#!/usr/bin/env python3
"""Texas Hold'em vs the machines — web version.

Run:  python webapp.py            (then open http://127.0.0.1:8000)
      python webapp.py --port 8080 --no-browser

See web/ for the implementation: web/session.py builds and runs a game on a
background thread, web/sink.py turns engine events into browser messages, and
web/server.py is the HTTP + SSE server.
"""

from web.server import main

if __name__ == "__main__":
    main()
