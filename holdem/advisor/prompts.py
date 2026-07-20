"""System prompt templates and the per-call prompt builders for the LLM coach."""

from __future__ import annotations

from ..brains.prompts import format_profiles
from ..players import RAISE
from .constants import GRADE_WORDS

ADVISE_SYSTEM = """You are {name}, {style}. You are NOT playing — you stand behind one player and tell them what to do.

You get: their cards, the board, the price they're facing, a Monte-Carlo estimate of how often they win against random hands, and what every opponent has actually DONE this hand. You do NOT get to see anyone's hole cards, and you must never pretend to. Your reads come from betting patterns only.

Respond with JSON only:
{{"action": "fold" | "check" | "call" | "raise" | "all_in",
  "raise_to": <total chips for this street, only when action is "raise">,
  "confidence": <0.0-1.0>,
  "line": "<one short sentence, said out loud to the player>",
  "reasoning": "<2-3 sentences: the price, the read, the decision>",
  "reads": [{{"name": "<opponent>", "note": "<short read on their likely range>"}}]}}

Be concrete about the money. The maths matters more than your gut, but a table that is screaming at you is real information the maths does not have — say when you're overriding the number and why. Never hedge into uselessness: pick one action.

The player sat down to PLAY. Preflop, respect the starting-hand yardstick you're given: a playable hand getting a cheap price is a call or a raise, not a fold — multiway equity against random hands understates it badly, because most of those hands fold long before the river. Save the discipline for real money against real strength, and when a spot is close, lean toward the disciplined aggressive line over the nitty one."""


# Who the coach is talking to. Appended to every system prompt, like the
# language note — "standard" adds nothing.
MODE_NOTES = {
    "beginner": "\n\nYour player is brand new to poker. Coach like a patient "
        "teacher: plain words, and the moment you use a poker term, explain it "
        "in one short clause — e.g. 'pot odds — the share of the pot you'd be "
        "paying', 'the flop — the first three shared cards'. Tie advice to "
        "what's on their screen: the Fold / Check / Call / Raise buttons and "
        "the raise slider. One idea at a time; never assume they know the "
        "jargon.",
    "pro": "\n\nYour player is experienced. Coach at full density: ranges and "
        "combos, blockers, sizing and stack-to-pot ratio, what each line "
        "represents, and the plan for later streets. Skip every basic — no "
        "term needs explaining, no hand-holding.",
}


def _mode_note(mode):
    return MODE_NOTES.get(mode, "")


# Sharpness policy, shared by every talking prompt: the coach may needle, but
# only off the evidence in front of it.
_EARNED_EDGE = " Sharpness must be earned: needle them only when the record in front of you shows the same mistake more than once; otherwise stay dry, fair and constructive."

VERDICT_SYSTEM = """You are {name}, {style}. The hand just ended. You told the player what to do; now you find out whether you were right.

Say ONE short sentence to them, out loud. Match the tone you're given:
- told_you: they listened and it worked. Be smug about it, briefly.
- vindicated: they ignored you and it cost them. "I did say."
- humbled: you were WRONG. Own it — self-deprecating, no excuses, no lecturing.
- shrug: nothing conclusive. Don't manufacture drama.

Never explain at length, never moralize, never repeat the numbers back.{edge} One sentence. No JSON, no quotes around it."""

DEFIANCE_SYSTEM = """You are {name}, {style}. You just told the player what to do and they did something else, right in front of you.

Say ONE short sentence reacting to what they actually did. Dry, not preachy — you'll find out soon enough who was right.{edge} No JSON, no quotes."""

SEND_OFF_SYSTEM = """You are {name}, {style}. The player is standing up from the table — the session is over, and this is your closing statement as you walk them out.

Speak 2-4 short sentences: the night in one honest line, the one thing they genuinely did well, the one habit that needs fixing (only if their record shows one), and a send-off worth remembering. Warm, dry, in character.{edge} Never recite the numbers back, no lists, no JSON, no quotes."""

REVIEW_SYSTEM = """You are {name}, {style}. The hand is over and you are debriefing your player — not one move, the whole hand.

You get every decision you advised on: what you said, what they did, and a process grade computed from the numbers at the time ("fine" means the move was correct). You also get their running record for the session.

Write 2-3 short spoken sentences. Judge the PROCESS, never the result — a correct call that lost money was still correct, and when that happened you say so out loud. Pick the ONE thing most worth fixing (or praising) this hand. If the session record shows the same mistake repeating, name the habit plainly.{edge} Don't recite the numbers back, don't make lists, don't lecture. No JSON, no quotes."""


def _one_sentence(raw):
    """First line, unquoted, trimmed — the model's spoken output, tidied."""
    text = str(raw or "").strip()
    if not text:
        return None
    line = text.splitlines()[0].strip().strip('"').strip()
    return line[:200] or None


def _board_text(board):
    return " ".join(str(c) for c in board) if board else "(nothing yet)"


def build_advice_prompt(view, odds_payload, base):
    hero = view["hero"]
    lines = [
        "Your player: %s. Stack %d." % (hero["name"], hero["stack"]),
        "Their cards: %s" % " ".join(str(c) for c in hero["hole"]),
        "Board: %s   Street: %s   Pot: %d" % (_board_text(view["board"]),
                                              view["street"], view["pot"]),
    ]
    if view["to_call"] > 0:
        lines.append("To call: %d  (pot odds %.0f%% — they must win that often to break even)"
                     % (view["to_call"], base["pot_odds"] * 100))
    else:
        lines.append("Nothing to call — checking is free.")
    if view["can_raise"]:
        lines.append("A raise must be to between %d and %d total this street."
                     % (view["min_raise_to"], view["max_raise_to"]))
    else:
        lines.append("They cannot raise here — only fold, call, or shove.")

    lines.append("")
    lines.append("Simulation vs random hands (%d rollouts): they win %.0f%% (tie %.0f%%)."
                 % (odds_payload["samples"], odds_payload["equity"] * 100,
                    odds_payload["tie"] * 100))
    made = odds_payload.get("made")
    if made:
        lines.append("Holding right now: %s" % made["name"])
    outs = [c for c in odds_payload["categories"] if c["make"] >= 0.02]
    if outs:
        lines.append("Where their equity comes from: " + ", ".join(
            "%s %.0f%% of the time (worth %.0f%% of the pot)"
            % (c["name"], c["make"] * 100, c["win"] * 100) for c in outs[:5]))

    lines.append("")
    lines.append("What each live opponent has DONE this hand, and what a Bayesian "
                 "read of it says they hold:")
    lines.append(format_actions(view["actions"], view["players"], base["reads"]))
    live = {p["name"] for p in view["players"]
            if not p["is_hero"] and not p["folded"]}
    book = [r for r in view.get("profiles") or [] if r["name"] in live]
    if book:
        lines.append("")
        lines.append("Tonight's book on them (the public record, across hands):")
        lines.append(format_profiles(book))
    lines.append("")
    if base.get("vs_range"):
        lines.append("Against random hands they win %.0f%%. Re-simulated against the "
                     "ranges above — the hands these opponents are actually "
                     "representing — they win %.0f%%. That second number is the real one."
                     % (base["equity"] * 100, base["adjusted"] * 100))
    else:
        lines.append("They win %.0f%% against random hands (%.0f%% once the read is "
                     "taken into account)." % (base["equity"] * 100, base["adjusted"] * 100))
    if base.get("preflop_tier") is not None:
        tier_word = {3: "premium", 2: "strong", 1: "playable",
                     0: "junk"}[base["preflop_tier"]]
        lines.append("PREFLOP YARDSTICK: their starting hand is %s, and the call "
                     "costs %.1f big blinds. The multiway simulation above "
                     "understates playable hands preflop (most opponents fold "
                     "before the river) — your arithmetic priced the decision on "
                     "the starting hand, not on that number. Do the same."
                     % (tier_word, base.get("preflop_cost") or 0.0))
    lines.append("Your own arithmetic says: %s%s, against a %.0f%% price."
                 % (base["action"],
                    (" to %d" % base["amount"]) if base["amount"] else "",
                    base["pot_odds"] * 100))
    lines.append("Agree or overrule it, but decide. The range percentages above are "
                 "yours to interpret, not to repeat — say what they mean. Respond with "
                 "the JSON object only.")
    return "\n".join(lines)


def format_actions(actions, players, reads=None):
    reads = {r["name"]: r for r in (reads or [])}
    live = {p["name"] for p in players if not p["is_hero"] and not p["folded"]}
    rows = []
    for info in players:
        if info["is_hero"]:
            continue
        mine = [a for a in actions if a["name"] == info["name"]]
        state = "still in" if info["name"] in live else "FOLDED"
        moves = (", ".join("%s: %s" % (a["street"].lower(), a["desc"]) for a in mine)
                 or "nothing yet")
        rows.append("- %s (%s, stack %d): %s"
                    % (info["name"], state, info["stack"], moves))
        read = reads.get(info["name"])
        if read and read.get("buckets"):
            shape = ", ".join("%.0f%% %s" % (b["p"] * 100, b["key"]) for b in read["buckets"])
            row = "    range now: %s" % shape
            if read.get("bluff") is not None:
                row += "  ->  bluffing about %.0f%% of the time" % (read["bluff"] * 100)
            rows.append(row)
    return "\n".join(rows) or "- (nobody has acted yet)"


def build_review_prompt(ctx):
    lines = ["Hand #%d just ended. Net for your player: %+d chips."
             % (ctx["hand_no"], ctx["net"]),
             "", "Their decisions this hand:"]
    for r in ctx["decisions"]:
        advised = r["advised"]["action"]
        if advised == RAISE and r["advised"]["amount"]:
            advised = "raise to %d" % r["advised"]["amount"]
        lines.append("- %s: you said %s, they %s. Their equity vs ranges was %.0f%%, "
                     "the price %.0f%%. Grade: %s"
                     % (r["street"].lower(), advised, r["did"],
                        r["equity"] * 100, r["price"] * 100,
                        GRADE_WORDS.get(r["grade"], "fine")))
    s = ctx["session"]
    lines.append("")
    lines.append("Session so far: %d hands; they followed %d of %d advised decisions; "
                 "net %+d on hands where they listened, %+d where they went their own way."
                 % (s["hands"], s["followed"], s["decisions"],
                    s["net_followed"], s["net_defied"]))
    leaks = ", ".join("%s ×%d" % (GRADE_WORDS[k], n)
                      for k, n in (s.get("mistakes") or {}).items())
    if leaks:
        lines.append("Recurring mistakes: %s." % leaks)
    lines.append("")
    lines.append("Debrief them now, out loud, 2-3 sentences.")
    return "\n".join(lines)


def build_verdict_prompt(context, tone):
    advice = context.get("advice") or {}
    lines = [
        "Tone you must take: %s" % tone,
        "You told them: %s%s" % (advice.get("action", "(nothing)"),
                                 (" to %d" % advice["amount"]) if advice.get("amount") else ""),
        "Your line at the time: \"%s\"" % (advice.get("line") or ""),
        "They actually: %s" % context["action_desc"],
        "They %s your advice." % ("followed" if context["followed"] else "IGNORED"),
        "Result: %s%d chips on the hand." % ("+" if context["net"] >= 0 else "", context["net"]),
    ]
    if context.get("hero_hand"):
        lines.append("They ended with: %s" % context["hero_hand"])
    if context.get("winner_hand"):
        lines.append("The hand was won with: %s" % context["winner_hand"])
    if context.get("would_have_won") is True:
        lines.append("IMPORTANT: they folded a hand that would have WON the pot.")
    if context.get("right") is False:
        lines.append("Your advice was WRONG. Do not weasel out of it.")
    elif context.get("right") is True:
        lines.append("Your advice was RIGHT.")
    lines.append("")
    lines.append("One sentence, out loud, to them. No quotes.")
    return "\n".join(lines)
