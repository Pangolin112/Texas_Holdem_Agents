"""Texas Hold'em vs the machines — web version.

Same game, same brains, same rules as the terminal (`main.py`): this package
adds a browser front-end with a 2D table instead of a text one. It does NOT
reimplement any poker logic. The real, shared engine (`holdem.game`,
`holdem.brains`, `holdem.evaluator`, ...) runs unchanged in a background thread;
a `WebSink` installed on that thread (see `holdem.ui.set_sink`) turns every game
event into a JSON message streamed to the browser over Server-Sent Events, and
feeds the player's clicks back in as the very same command strings the terminal
accepts ("f", "c", "r 120", "a", "say ...", "buy 200", "q").

Because both front-ends drive one engine, any new game feature added to the
engine shows up in the terminal and the web version at once — the guiding rule
for this project.
"""
