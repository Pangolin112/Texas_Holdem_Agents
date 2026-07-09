/* ===================== Texas Hold'em — web client =====================
 * Talks to webapp.py: POST /api/new to start, an EventSource on /api/events
 * for the live game stream, POST /api/input to send the same command strings
 * the terminal accepts ("f", "c", "r 120", "a", "say ...", "buy 200").
 * The engine (and the AI brains) live entirely in Python — this file only
 * draws the table and forwards clicks.
 * ==================================================================== */

const $ = (id) => document.getElementById(id);

// Where the Python engine (webapp.py) is reachable. Empty string = same origin
// (webapp.py is serving this page); a full https URL when a GitHub Pages
// front-end talks to a separately hosted backend. See config.js.
const API = (window.HOLDEM_BACKEND || "").replace(/\/+$/, "");

const G = {
  sid: null,
  es: null,
  state: null,        // newest table snapshot
  legal: null,        // legal-move info while it's our turn
  mode: null,         // "action" | "between" | "text" | null
  thinking: null,     // name of the seat currently deciding (transient)
  seatPos: {},        // name -> {x, y} in table % coords
  meta: {},
  summary: null,      // finished-hand recap, shown until the next deal
  actions: {},        // name -> {t, k}: each seat's latest move this street
};

// turn an engine action phrase ("raises to 120", "calls 20 (all-in)") into a
// short chip label + a kind used for its color.
function actionLabel(desc) {
  const d = desc.toLowerCase();
  const num = (desc.match(/(\d+)/) || [])[1];
  const n = num ? " " + num : "";
  if (d.includes("fold")) return { t: "Fold", k: "fold" };
  if (d.includes("small blind")) return { t: "SB" + n, k: "post" };
  if (d.includes("big blind")) return { t: "BB" + n, k: "post" };
  if (d.includes("all-in") || d.includes("all in")) return { t: "All-in" + n, k: "allin" };
  if (d.startsWith("checks")) return { t: "Check", k: "check" };
  if (d.startsWith("calls")) return { t: "Call" + n, k: "call" };
  if (d.startsWith("bets")) return { t: "Bet" + n, k: "bet" };
  if (d.startsWith("raises")) return { t: "Raise" + n, k: "raise" };
  return { t: desc, k: "other" };
}

function resetSummary() {
  G.summary = { handNo: G.state ? G.state.hand_no : 0, lines: [], winners: {}, active: false };
  const el = $("summary");
  if (el) { el.classList.add("hidden"); el.innerHTML = ""; }
}

/* ------------------------- setup ------------------------- */

$("deal-in").addEventListener("click", startGame);
$("btn-help").addEventListener("click", () => $("help").classList.remove("hidden"));
$("help-close").addEventListener("click", () => $("help").classList.add("hidden"));
$("btn-leave").addEventListener("click", leaveTable);

function startGame() {
  const options = {
    name: $("opt-name").value || "You",
    opponents: clampInt($("opt-opponents").value, 1, 7, 5),
    stack: clampInt($("opt-stack").value, 20, 1e9, 1000),
    sb: clampInt($("opt-sb").value, 1, 1e9, 10),
    bb: clampInt($("opt-bb").value, 2, 1e9, 20),
    model: $("opt-model").value.trim() || undefined,
    offline: $("opt-offline").checked,
    show_cards: $("opt-showcards").checked,
    seed: $("opt-seed").value === "" ? null : clampInt($("opt-seed").value, 0, 1e12, null),
  };
  if (G.accessCode) options.access_code = G.accessCode;
  $("setup-note").textContent = API
    ? "Dealing you in… (a sleeping free server can take ~30s to wake the first time)"
    : "Shuffling…";
  fetch(API + "/api/new", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  })
    .then((r) => {
      if (r.status === 403) {          // host set an access code — ask and retry
        const code = prompt("This table needs an access code to sit down:");
        if (code) { G.accessCode = code; startGame(); }
        else $("setup-note").textContent = "An access code is required to play.";
        return null;
      }
      return r.json();
    })
    .then((data) => {
      if (!data) return;               // 403 branch handled it
      if (!data.sid) {
        $("setup-note").textContent = data.error || "Could not start the game.";
        return;
      }
      G.sid = data.sid;
      $("setup").classList.add("hidden");
      $("game").classList.remove("hidden");
      connect();
    })
    .catch(() => {
      $("setup-note").textContent = API
        ? "Couldn't reach the game server — it may be waking up. Try again in a moment."
        : "Could not start the game.";
    });
}

function clampInt(v, lo, hi, dflt) {
  const n = parseInt(v, 10);
  if (isNaN(n)) return dflt;
  return Math.max(lo, Math.min(hi, n));
}

/* ------------------------- SSE stream ------------------------- */

function connect() {
  G.es = new EventSource(API + "/api/events?sid=" + G.sid);
  G.es.onmessage = (e) => {
    let ev;
    try { ev = JSON.parse(e.data); } catch (_) { return; }
    handle(ev);
  };
  G.es.onerror = () => { /* EventSource auto-reconnects; server re-syncs. */ };
}

function handle(ev) {
  if (ev.state) G.state = ev.state;

  switch (ev.type) {
    case "start":
      G.meta = ev.meta || {};
      if (G.meta.note) feed(G.meta.note, "sys");
      break;
    case "hand_start":
      clearBubbles(); hideAward();
      resetSummary();
      G.actions = {};
      G.thinking = null;
      feed(`— Hand #${ev.hand_no} · blinds ${ev.sb}/${ev.bb} · dealer ${ev.dealer} —`, "sys");
      break;
    case "street":
      G.actions = {};   // fresh street — clear last-move chips
      feed(`${ev.street}`, "sys");
      break;
    case "action":
      G.thinking = null;
      G.actions[ev.name] = actionLabel(ev.desc);
      feed(`<span class="who">${esc(ev.name)}</span> ${esc(ev.desc)}.`);
      break;
    case "thinking":
      G.thinking = ev.name;
      break;
    case "chat":
      if (ev.name === G.thinking) G.thinking = null;  // their reply arrived
      showBubble(ev.name, ev.text, ev.to);
      feed(`<span class="who">${esc(ev.name)}</span>${ev.to ? ` (to ${esc(ev.to)})` : ""}: "${esc(ev.text)}"`, "chat");
      break;
    case "reveal":
      feed("All-in — cards on their backs.", "sys");
      break;
    case "showdown":
      (ev.players || []).forEach((p) =>
        feed(`<span class="who">${esc(p.name)}</span> shows ${cardsText(p.cards)} — ${esc(p.hand)}`));
      break;
    case "peek":
      (ev.players || []).forEach((p) =>
        feed(`<span class="who">${esc(p.name)}</span> had ${cardsText(p.cards)}${p.folded ? " (folded)" : ""}${p.hand ? " — " + esc(p.hand) : ""}`, "sys"));
      break;
    case "pot_award":
      feed(ev.text, "pot");
      recordAward(ev.text);
      break;
    case "buy":
      feed(`<span class="who">${esc(ev.name)}</span> buys in for ${ev.amount} (tab ${ev.debt}).`, "sys");
      break;
    case "rebuy":
      feed(`<span class="who">${esc(ev.name)}</span> is felted — restaked ${ev.stake} (tab ${ev.debt}).`, "sys");
      if (ev.line) showBubble(ev.name, ev.line, null);
      break;
    case "standings":
      renderStandings(ev);
      break;
    case "await":
      onAwait(ev);
      break;
    case "log":
      if (ev.text) feed(ev.text, ev.level === "warn" || ev.level === "error" ? "warn" : "sys");
      break;
    case "game_over":
      onGameOver();
      break;
    case "fatal":
      $("setup").classList.remove("hidden");
      $("game").classList.add("hidden");
      $("setup-note").textContent = ev.text || "Game error.";
      break;
    case "sync": case "ping": case "closed": break;
  }

  render();
}

/* ------------------------- input requests ------------------------- */

function onAwait(ev) {
  G.mode = ev.mode;
  if (ev.mode === "action") {
    G.legal = ev.legal || {};
    showActionControls();
  } else if (ev.mode === "between") {
    showBetweenControls(ev.allowance || 0);
  } else {
    // generic text prompt (e.g. a confirm) — feed it and let the say box answer raw
    feed(ev.prompt || "…", "sys");
    setControls("text");
  }
}

function setControls(which) {
  const c = $("controls"), b = $("between");
  c.classList.toggle("hidden", which !== "action");
  b.classList.toggle("hidden", which !== "between");
  c.classList.toggle("disabled", which !== "action");
  b.classList.toggle("disabled", which !== "between");
}

function showActionControls() {
  setControls("action");
  const L = G.legal || {};
  const toCall = L.to_call || 0;
  const heroStack = L.hero_stack || 0;

  // fold only matters when facing a bet
  $("act-fold").classList.toggle("hidden", toCall <= 0);

  const callBtn = $("act-call");
  if (toCall <= 0) {
    callBtn.textContent = "Check";
  } else if (toCall >= heroStack) {
    callBtn.textContent = `Call ${heroStack} (all-in)`;
  } else {
    callBtn.textContent = `Call ${toCall}`;
  }

  $("act-raise").classList.toggle("hidden", !L.can_raise);
  $("raise-panel").classList.add("hidden");

  const hint = L.hero_hand_hint ? `You have ${L.hero_hand_hint}` : "Your move.";
  $("hero-hint").textContent = hint;
}

$("act-fold").addEventListener("click", () => act("f"));
$("act-call").addEventListener("click", () => act("c"));
$("act-allin").addEventListener("click", () => act("a"));
$("act-raise").addEventListener("click", openRaisePanel);
$("raise-go").addEventListener("click", () => {
  const amt = clampInt($("raise-amount").value, G.legal.min_raise_to, G.legal.max_raise_to, G.legal.min_raise_to);
  if (amt >= G.legal.max_raise_to) act("a"); else act("r " + amt);
});

function openRaisePanel() {
  const L = G.legal;
  const panel = $("raise-panel");
  panel.classList.toggle("hidden");
  if (panel.classList.contains("hidden")) return;
  const slider = $("raise-slider");
  slider.min = L.min_raise_to; slider.max = L.max_raise_to; slider.value = L.min_raise_to;
  $("raise-amount").value = L.min_raise_to;
  slider.oninput = () => { $("raise-amount").value = slider.value; };
  $("raise-amount").oninput = () => { slider.value = clampInt($("raise-amount").value, L.min_raise_to, L.max_raise_to, L.min_raise_to); };
}

document.querySelectorAll(".chip-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const L = G.legal; const frac = btn.dataset.frac;
    let amt;
    if (frac === "min") amt = L.min_raise_to;
    else if (frac === "max") amt = L.max_raise_to;
    else {
      const toCall = L.to_call || 0;
      const callTotal = (L.hero_bet || 0) + toCall;      // level after calling
      const potAfter = (L.pot || 0) + toCall;
      amt = Math.round(callTotal + parseFloat(frac) * potAfter);
    }
    amt = Math.max(L.min_raise_to, Math.min(L.max_raise_to, amt));
    $("raise-amount").value = amt;
    $("raise-slider").value = amt;
  });
});

/* action: send a command and lock controls until the next request */
function act(line) {
  if (!G.sid) return;
  postInput(line);
  G.mode = null; G.legal = null;
  $("controls").classList.add("disabled");
  $("hero-hint").textContent = "";
}

function postInput(line) {
  fetch(API + "/api/input?sid=" + G.sid, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ line }),
  }).catch(() => {});
}

/* between hands */
function showBetweenControls(allowance) {
  setControls("between");
  const buy = $("buy-amount");
  buy.max = allowance; buy.value = 0;
  buy.disabled = allowance <= 0;
  $("buy-go").disabled = allowance <= 0;
  $("buy-allow").textContent = allowance > 0 ? `up to ${allowance}` : "(max reached this hand)";
  $("hero-hint").textContent = "Hand over — deal the next one, or buy in.";
}

$("next-hand").addEventListener("click", () => {
  $("between").classList.add("disabled");
  G.mode = null;
  postInput("");
});
$("buy-go").addEventListener("click", () => {
  const amt = clampInt($("buy-amount").value, 0, 1e9, 0);
  if (amt > 0) postInput("buy " + amt);
});

/* say box: normally "say X"; in text mode sends the raw line */
$("say-go").addEventListener("click", sendSay);
$("say-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendSay(); });
function sendSay() {
  const t = $("say-input").value.trim();
  if (!t) return;
  $("say-input").value = "";
  postInput(G.mode === "text" ? t : "say " + t);
  if (G.mode === "text") G.mode = null;
}

function leaveTable() {
  if (!G.sid) return;
  fetch(API + "/api/quit?sid=" + G.sid, { method: "POST" }).catch(() => {});
}

function onGameOver() {
  if (G.es) { G.es.close(); G.es = null; }
  setControls("none");
  $("hero-hint").textContent = "";
  $("mode-label").textContent = "game over";
  showAward("Game over — thanks for playing! Refresh to sit down again.");
}

/* ------------------------- rendering ------------------------- */

function render() {
  const s = G.state;
  if (!s) return;

  // top bar
  $("hand-label").textContent = s.hand_no ? `Hand #${s.hand_no}` : "—";
  $("blinds-label").textContent = `blinds ${s.sb}/${s.bb}`;
  const ml = $("mode-label");
  if (s.live) { ml.textContent = s.street || "in play"; ml.classList.add("live"); }
  else { ml.textContent = "between hands"; ml.classList.remove("live"); }

  // pot + street tag + board
  const pot = $("pot");
  if (s.live && s.pot > 0) { pot.classList.remove("hidden"); $("pot-amt").textContent = s.pot; }
  else pot.classList.add("hidden");
  $("street-tag").textContent = s.live ? (s.street || "") : "";
  renderBoard(s.board || []);

  // seats
  const seats = s.seats || [];
  const n = seats.length;
  const seatsEl = $("seats"); seatsEl.innerHTML = "";
  const betsEl = $("bets"); betsEl.innerHTML = "";
  G.seatPos = {};

  const rx = 41, ry = 40;                 // ellipse radii (% of table)
  seats.forEach((seat, i) => {
    const ang = (Math.PI / 180) * (90 + i * (360 / n));  // seat 0 = bottom
    const x = 50 + rx * Math.cos(ang);
    const y = 50 + ry * Math.sin(ang);
    G.seatPos[seat.name] = { x, y };
    seatsEl.appendChild(seatEl(seat, x, y));

    if (seat.bet > 0) {
      const bx = 50 + rx * 0.55 * Math.cos(ang);
      const by = 50 + ry * 0.55 * Math.sin(ang);
      betsEl.appendChild(betEl(seat.bet, bx, by));
    }
  });

  // dealer button near the button seat
  const dbtn = $("dealer-btn");
  const btnSeat = seats[s.button];
  if (s.live && btnSeat && G.seatPos[btnSeat.name]) {
    const ang = (Math.PI / 180) * (90 + s.button * (360 / n));
    dbtn.style.left = (50 + rx * 0.72 * Math.cos(ang) + 6) + "%";
    dbtn.style.top = (50 + ry * 0.72 * Math.sin(ang)) + "%";
    dbtn.classList.remove("hidden");
  } else dbtn.classList.add("hidden");

  renderSummary();
}

function seatEl(seat, x, y) {
  const el = document.createElement("div");
  el.className = "seat" + (seat.is_human ? " hero-seat" : "");
  const won = (G.summary && G.summary.active) ? (G.summary.winners[seat.name] || 0) : 0;
  if (seat.folded && !won) el.classList.add("folded");
  const isTurn = (seat.name === G.thinking) || (G.mode === "action" && seat.is_human);
  if (isTurn && G.state.live) el.classList.add("turn");
  if (won) el.classList.add("winner");
  el.style.left = x + "%"; el.style.top = y + "%";

  // cards row
  const cardsRow = document.createElement("div");
  cardsRow.className = "seat-cards";
  const mini = !seat.is_human;
  if (seat.cards) {
    seat.cards.forEach((c) => cardsRow.appendChild(cardEl(c, mini)));
  } else if (seat.card_count > 0) {
    for (let k = 0; k < seat.card_count; k++) cardsRow.appendChild(backEl(mini));
  }

  const body = document.createElement("div");
  body.className = "seat-body";
  // status line under the name: while deciding show "thinking…", otherwise the
  // seat's latest move this street (falling back to its folded/all-in state).
  let status = "";
  if (seat.name === G.thinking && G.state.live) {
    status = `<span class="badge think">thinking…</span>`;
  } else {
    let act = G.actions[seat.name];
    if (!act) {
      if (seat.folded) act = { t: "Fold", k: "fold" };
      else if (seat.all_in) act = { t: "All-in", k: "allin" };
    }
    if (act) status = `<span class="act-chip k-${act.k}">${esc(act.t)}</span>`;
  }
  body.innerHTML =
    `<div class="seat-name">${esc(seat.name)}</div>` +
    `<div class="seat-stack">$${seat.stack}</div>` +
    (seat.debt ? `<div class="seat-debt">tab ${seat.debt}</div>` : "") +
    `<div class="seat-badges">${status}</div>`;

  el.appendChild(cardsRow);
  el.appendChild(body);
  if (won) {
    const wb = document.createElement("div");
    wb.className = "win-badge";
    wb.textContent = "+" + won;
    el.appendChild(wb);
  }
  return el;
}

function betEl(amount, x, y) {
  const el = document.createElement("div");
  el.className = "bet";
  el.style.left = x + "%"; el.style.top = y + "%";
  el.innerHTML = `<span class="disc"></span>${amount}`;
  return el;
}

function renderBoard(board) {
  const el = $("board"); el.innerHTML = "";
  for (let i = 0; i < 5; i++) {
    if (i < board.length) el.appendChild(cardEl(board[i], false));
    else {
      const slot = document.createElement("div");
      slot.className = "card"; slot.style.visibility = "hidden";
      el.appendChild(slot);
    }
  }
}

function cardEl(c, mini) {
  const el = document.createElement("div");
  el.className = "card" + (c.red ? " red" : "") + (mini ? " mini" : "");
  el.innerHTML =
    `<div class="corner"><span>${c.rank}</span><span>${c.symbol}</span></div>` +
    `<div class="rank">${c.rank}</div><div class="pip">${c.symbol}</div>` +
    `<div class="corner br"><span>${c.rank}</span><span>${c.symbol}</span></div>`;
  return el;
}

function backEl(mini) {
  const el = document.createElement("div");
  el.className = "card back" + (mini ? " mini" : "");
  return el;
}

/* speech bubbles anchored above a seat */
function showBubble(name, text, to) {
  const pos = G.seatPos[name];
  if (!pos) return;
  const table = $("table");
  const old = table.querySelector(`.bubble[data-seat="${cssEsc(name)}"]`);
  if (old) old.remove();
  const b = document.createElement("div");
  b.className = "bubble"; b.dataset.seat = name;
  b.style.left = pos.x + "%"; b.style.top = (pos.y - 9) + "%";
  b.innerHTML = (to ? `<span class="to">@${esc(to)} </span>` : "") + esc(text);
  table.appendChild(b);
  setTimeout(() => b.remove(), 4600);
}
function clearBubbles() {
  document.querySelectorAll("#table .bubble").forEach((b) => b.remove());
}

function showAward(text) {
  const a = $("award"); a.textContent = text; a.classList.remove("hidden");
  clearTimeout(G._awardT);
  G._awardT = setTimeout(hideAward, 4200);
}
function hideAward() { $("award").classList.add("hidden"); }

/* ---- finished-hand summary (stays on the felt until the next deal) ---- */

// The pot-award lines are worded by the engine; pull the winner(s) + amount
// out so we can glow the seats and stack a "+chips" badge on them. If a line
// doesn't parse we still show its text — nothing is lost.
function parseAward(text) {
  let m;
  if ((m = text.match(/^(.+?) takes back (\d+)/)))
    return { names: [m[1].trim()], amount: +m[2] };
  if ((m = text.match(/^(.+?) split the .*?of (\d+)/)))
    return { names: m[1].split(" and ").map((s) => s.trim()), amount: +m[2] };
  if ((m = text.match(/^(.+?) wins? the .*?of (\d+)/)))
    return { names: [m[1].trim()], amount: +m[2] };
  return null;
}

function recordAward(text) {
  if (!G.summary) resetSummary();
  G.summary.handNo = G.state ? G.state.hand_no : G.summary.handNo;
  G.summary.lines.push(text);
  G.summary.active = true;
  const w = parseAward(text);
  if (w) {
    const share = Math.floor(w.amount / w.names.length);
    w.names.forEach((n) => { G.summary.winners[n] = (G.summary.winners[n] || 0) + share; });
    flyChips(w.names);
  }
  renderSummary();
}

function renderSummary() {
  const el = $("summary");
  if (!el) return;
  if (!G.summary || !G.summary.active || !G.summary.lines.length) {
    el.classList.add("hidden"); return;
  }
  el.classList.remove("hidden");
  el.innerHTML =
    `<div class="sum-title">Hand #${G.summary.handNo} — result</div>` +
    G.summary.lines.map((l) => `<div class="sum-line">🏆 ${esc(l)}</div>`).join("");
}

// a few gold chips sliding from the pot toward each winner
function flyChips(names) {
  const table = $("table");
  names.forEach((n) => {
    const pos = G.seatPos[n];
    if (!pos) return;
    for (let j = 0; j < 6; j++) {
      const chip = document.createElement("div");
      chip.className = "fly-chip";
      chip.style.left = "50%"; chip.style.top = "43%";
      chip.style.transitionDelay = (j * 70) + "ms";
      table.appendChild(chip);
      requestAnimationFrame(() => {
        chip.style.left = pos.x + "%";
        chip.style.top = pos.y + "%";
        chip.style.opacity = "0.15";
      });
      setTimeout(() => chip.remove(), 1100 + j * 70);
    }
  });
}

/* ------------------------- feed + standings ------------------------- */

function feed(html, cls) {
  const list = $("feed-list");
  const item = document.createElement("div");
  item.className = "feed-item" + (cls ? " " + cls : "");
  item.innerHTML = html;
  list.appendChild(item);
  while (list.children.length > 200) list.removeChild(list.firstChild);
  list.scrollTop = list.scrollHeight;
}

function renderStandings(ev) {
  let rows = ev.rows.map((r) => {
    const net = r.net >= 0 ? "+" + r.net : "" + r.net;
    const tab = r.debt ? ` · tab ${r.debt} · net ${net}` : "";
    return `${r.is_human ? "★ " : ""}${esc(r.name)} — $${r.stack}${tab}`;
  });
  feed(`<b>${esc(ev.title)}:</b><br>` + rows.join("<br>"), "sys");
}

/* ------------------------- helpers ------------------------- */

function cardsText(cards) {
  return (cards || []).map((c) => c.rank + c.symbol).join(" ");
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function cssEsc(s) { return String(s).replace(/["\\]/g, "\\$&"); }
