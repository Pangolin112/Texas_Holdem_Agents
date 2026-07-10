/* ===================== Texas Hold'em — web client =====================
 * Talks to webapp.py: POST /api/new to start, an EventSource on /api/events
 * for the live game stream, POST /api/input to send the same command strings
 * the terminal accepts ("f", "c", "r 120", "a", "say ...", "buy 200").
 * The engine (and the AI brains) live entirely in Python — this file only
 * draws the table and forwards clicks. UI language is handled here (EN/中文):
 * the engine always emits English event text, and the client translates the
 * few fixed phrase shapes for display. voice.js adds speech in/out on top.
 * ==================================================================== */

const $ = (id) => document.getElementById(id);

/* ------------------------- i18n ------------------------- */

const I18N = {
  en: {
    page_title: "Texas Hold'em — you vs. the machines",
    title_sub: "No-Limit Texas Hold'em",
    tagline: "You, against a table of AI regulars.",
    lbl_name: "Your name", lbl_lang: "Language / 语言", lbl_opponents: "Opponents",
    lbl_stack: "Starting stack", lbl_sb: "Small blind", lbl_bb: "Big blind",
    lbl_model: "Model",
    chk_offline: "Offline (built-in bots, no API)",
    chk_peek: "Peek mode (reveal cards after each hand)",
    lbl_seed: "Seed (optional, reproducible deck)", ph_seed: "random",
    deal_in: "Deal me in",
    shuffling: "Shuffling…",
    access_prompt: "This table needs an access code to sit down:",
    access_required: "An access code is required to play.",
    start_failed: "Could not start the game.",
    leave: "Leave", feed_head: "Table feed",
    fold: "Fold", check: "Check", raise: "Raise", allin: "All-in",
    call_n: "Call {n}", call_allin: "Call {n} (all-in)",
    half_pot: "½ pot", threeq_pot: "¾ pot", one_pot: "pot", min: "min", max: "max",
    raise_to: "raise to", confirm: "Confirm",
    next_hand: "Next hand ▸", buy_chips: "Buy chips", top_up: "Top up",
    buy_upto: "up to {n}", buy_max: "(max reached this hand)",
    ph_say: "Say something to the table…  (they hear you and answer)", say: "Say",
    your_move: "Your move.", you_have: "You have {hand}",
    hand_over: "Hand over — deal the next one, or buy in.",
    hand_no: "Hand #{n}", blinds: "blinds {sb}/{bb}",
    between_hands: "between hands", in_play: "in play", mode_over: "game over",
    thinking: "thinking…",
    feed_hand: "— Hand #{n} · blinds {sb}/{bb} · dealer {dealer} —",
    allin_reveal: "All-in — cards on their backs.",
    shows: "shows", had: "had", folded_paren: " (folded)",
    to_x: " (to {x})",
    feed_buy: "buys in for {amount} (tab {debt}).",
    feed_felted: "is felted — restaked {stake} (tab {debt}).",
    sum_title: "Hand #{n} — result",
    game_over_msg: "Game over — thanks for playing! Refresh to sit down again.",
    note_offline: "Offline mode: opponents run on built-in instincts, no API calls.",
    note_online: "Opponents powered by OpenAI model: {model} (auto-fallback if unavailable).",
    tab_net: " · tab {debt} · net {net}",
    heard: "heard",
    help_title: "How to play",
    help_1: "<b>Fold / Check / Call</b> — the middle button knows whether you can check for free or must call.",
    help_2: "<b>Raise</b> — opens a slider; drag it or use the ½·¾·pot shortcuts, then Confirm.",
    help_3: "<b>All-in</b> — shove your whole stack.",
    help_4: "<b>Say</b> — talk to the table any time. Name someone and they answer; ask <i>why</i> they made a move and they'll explain their real reasoning.",
    help_5: "<b>Voice</b> — click 🎤 and speak: \"fold\", \"call\", \"raise to 200\", \"all in\" play the move; anything else is table talk. 🔊 lets the agents talk back out loud.",
    help_6: "<b>Between hands</b> — buy more chips (added to your tab) or deal the next hand.",
    help_note: "A player can bluff about their cards, but if they announce a move (\"I fold\", \"I'm all in\") the game forces the move to match.",
    got_it: "Got it",
  },
  zh: {
    page_title: "德州扑克 — 你 vs 机器",
    title_sub: "无限注德州扑克",
    tagline: "你，对阵一桌 AI 老牌友。",
    lbl_name: "你的名字", lbl_lang: "Language / 语言", lbl_opponents: "对手数量",
    lbl_stack: "起始筹码", lbl_sb: "小盲注", lbl_bb: "大盲注",
    lbl_model: "模型",
    chk_offline: "离线模式（内置机器人，不调用 API）",
    chk_peek: "偷看模式（每手结束后亮出所有底牌）",
    lbl_seed: "随机种子（可选，可复现的牌序）", ph_seed: "随机",
    deal_in: "发牌，我上桌",
    shuffling: "洗牌中…",
    access_prompt: "这张牌桌需要访问码才能入座：",
    access_required: "需要访问码才能开始游戏。",
    start_failed: "游戏启动失败。",
    leave: "离席", feed_head: "牌桌动态",
    fold: "弃牌", check: "过牌", raise: "加注", allin: "全下",
    call_n: "跟注 {n}", call_allin: "跟注 {n}（全下）",
    half_pot: "半池", threeq_pot: "¾池", one_pot: "一池", min: "最小", max: "最大",
    raise_to: "加注到", confirm: "确定",
    next_hand: "下一手 ▸", buy_chips: "买筹码", top_up: "补充",
    buy_upto: "最多 {n}", buy_max: "（本手已达上限）",
    ph_say: "对牌桌说点什么……（他们听得见，也会回话）", say: "说",
    your_move: "该你了。", you_have: "你现在是{hand}",
    hand_over: "这手结束了——发下一手，或买些筹码。",
    hand_no: "第 {n} 手", blinds: "盲注 {sb}/{bb}",
    between_hands: "两手之间", in_play: "进行中", mode_over: "游戏结束",
    thinking: "思考中…",
    feed_hand: "— 第 {n} 手 · 盲注 {sb}/{bb} · 庄家 {dealer} —",
    allin_reveal: "全下——底牌亮出来了。",
    shows: "亮出", had: "拿的是", folded_paren: "（已弃牌）",
    to_x: "（对 {x}）",
    feed_buy: "买入 {amount}（记账 {debt}）。",
    feed_felted: "输光了——庄家再借 {stake}（记账 {debt}）。",
    sum_title: "第 {n} 手 · 结果",
    game_over_msg: "游戏结束——多谢参与！刷新页面可以再来一局。",
    note_offline: "离线模式：对手使用内置逻辑，不调用 API。",
    note_online: "对手由 OpenAI 模型驱动：{model}（不可用时自动降级）。",
    tab_net: " · 记账 {debt} · 净值 {net}",
    heard: "听到",
    help_title: "怎么玩",
    help_1: "<b>弃牌 / 过牌 / 跟注</b> —— 中间的按钮会自动判断你能免费过牌还是必须跟注。",
    help_2: "<b>加注</b> —— 打开滑块；拖动它或用 半池·¾池·一池 快捷键，然后点确定。",
    help_3: "<b>全下</b> —— 推入你的全部筹码。",
    help_4: "<b>说话</b> —— 随时和牌桌聊天。点名谁，谁就会回答；问他们<i>为什么</i>那么打，他们会解释真实的思路。",
    help_5: "<b>语音</b> —— 点 🎤 开口说：“弃牌”“跟注”“加注到 200”“全下”会直接出牌；说别的就是牌桌聊天。开着 🔊，对手们会开口回话。",
    help_6: "<b>两手之间</b> —— 买更多筹码（记在账上）或发下一手。",
    help_note: "玩家可以在牌上虚张声势，但只要嘴上宣布了动作（“我弃了”“我全下”），游戏会强制动作和话一致。",
    got_it: "明白",
  },
};

function t(key, vars) {
  const table = I18N[G.lang] || I18N.en;
  let s = table[key] !== undefined ? table[key] : I18N.en[key];
  if (s === undefined) return key;
  if (vars) for (const k in vars) s = s.split("{" + k + "}").join(vars[k]);
  return s;
}

/* --- translators for the engine's fixed English phrases (display only) --- */

const STREETS_ZH = { PREFLOP: "翻牌前", FLOP: "翻牌", TURN: "转牌", RIVER: "河牌" };
function trStreet(s) {
  if (G.lang !== "zh" || !s) return s;
  return STREETS_ZH[String(s).toUpperCase()] || s;
}

const VAL_WORD = { two: "2", three: "3", four: "4", five: "5", six: "6", seven: "7",
                   eight: "8", nine: "9", ten: "10", jack: "J", queen: "Q",
                   king: "K", ace: "A" };
function valChar(w) {
  w = String(w).toLowerCase();
  if (VAL_WORD[w]) return VAL_WORD[w];
  const base = w.replace(/es$/, "").replace(/s$/, "");
  return VAL_WORD[base] || w;
}

function trHand(name) {
  if (G.lang !== "zh" || !name) return name;
  let m;
  if (/royal flush/i.test(name)) return "皇家同花顺";
  if ((m = name.match(/^a Straight Flush, (\w+) high$/i))) return "同花顺（" + valChar(m[1]) + "高）";
  if ((m = name.match(/^Four of a Kind, (\w+)$/i))) return "四条" + valChar(m[1]);
  if ((m = name.match(/^a Full House, (\w+) over (\w+)$/i))) return "葫芦（" + valChar(m[1]) + "带" + valChar(m[2]) + "）";
  if ((m = name.match(/^a Flush, (\w+) high$/i))) return "同花（" + valChar(m[1]) + "高）";
  if ((m = name.match(/^a Straight, (\w+) high$/i))) return "顺子（" + valChar(m[1]) + "高）";
  if ((m = name.match(/^Three of a Kind, (\w+)$/i))) return "三条" + valChar(m[1]);
  if ((m = name.match(/^Two Pair, (\w+) and (\w+)$/i))) return "两对（" + valChar(m[1]) + "和" + valChar(m[2]) + "）";
  if ((m = name.match(/^a Pair of (\w+)$/i))) return "一对" + valChar(m[1]);
  if ((m = name.match(/^High Card, (\w+)$/i))) return "高牌" + valChar(m[1]);
  return name;
}

function trActionDesc(desc) {
  if (G.lang !== "zh") return desc;
  let m;
  if (desc === "folds") return "弃牌";
  if (desc === "checks") return "过牌";
  if ((m = desc.match(/^calls (\d+) \(all-in\)$/))) return "跟注 " + m[1] + "（全下）";
  if ((m = desc.match(/^calls (\d+) and is all-in$/))) return "跟注 " + m[1] + "，全下";
  if ((m = desc.match(/^calls (\d+)$/))) return "跟注 " + m[1];
  if ((m = desc.match(/^bets (\d+)$/))) return "下注 " + m[1];
  if ((m = desc.match(/^raises to (\d+)$/))) return "加注到 " + m[1];
  if ((m = desc.match(/^goes ALL-IN for (\d+)$/))) return "全下 " + m[1];
  if ((m = desc.match(/^posts small blind (\d+)( \(all-in\))?$/))) return "下小盲 " + m[1] + (m[2] ? "（全下）" : "");
  if ((m = desc.match(/^posts big blind (\d+)( \(all-in\))?$/))) return "下大盲 " + m[1] + (m[2] ? "（全下）" : "");
  return desc;
}

function potWord(w) { return w === "side pot" ? "边池" : (w === "main pot" ? "主池" : "底池"); }

function trPot(text) {
  if (G.lang !== "zh" || !text) return text;
  let m;
  if ((m = text.match(/^(.+?) wins the pot of (\d+) — everyone else folded\.$/)))
    return m[1] + " 赢下底池 " + m[2] + "——其他人都弃牌了。";
  if ((m = text.match(/^(.+?) wins the (main pot|side pot|pot) of (\d+) with (.+)\.$/)))
    return m[1] + " 以" + trHand(m[4]) + "赢下" + potWord(m[2]) + " " + m[3] + "。";
  if ((m = text.match(/^(.+?) split the (main pot|side pot|pot) of (\d+) with (.+)\.$/)))
    return m[1].split(" and ").join(" 和 ") + " 以" + trHand(m[4]) + "平分" + potWord(m[2]) + " " + m[3] + "。";
  if ((m = text.match(/^(.+?) takes back (\d+) uncalled chips\.$/)))
    return m[1] + " 收回无人跟注的 " + m[2] + "。";
  return text;
}

const TITLES_ZH = { "standings": "当前排名", "final standings": "最终排名",
                    "chip counts when you left": "离席时的筹码" };
function trTitle(title) {
  if (G.lang !== "zh") return title;
  return TITLES_ZH[title] || title;
}

/* ------------------------- state ------------------------- */

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
  actions: {},        // name -> {key, n, k}: each seat's latest move this street
  accessCode: null,   // remembered ACCESS_CODE, if the host requires one
  lastAllowance: 0,   // last between-hands buy allowance (for re-render)
  lang: localStorage.getItem("holdem_lang")
        || ((navigator.language || "").toLowerCase().indexOf("zh") === 0 ? "zh" : "en"),
};

// turn an engine action phrase ("raises to 120", "calls 20 (all-in)") into a
// structured chip: a label key + amount + a kind used for its color. The label
// itself is rendered per-language at draw time (chipLabel).
function actionLabel(desc) {
  const d = desc.toLowerCase();
  const num = (desc.match(/(\d+)/) || [])[1];
  const n = num ? " " + num : "";
  if (d.includes("fold")) return { key: "fold", n: "", k: "fold" };
  if (d.includes("small blind")) return { key: "sb", n, k: "post" };
  if (d.includes("big blind")) return { key: "bb", n, k: "post" };
  if (d.includes("all-in") || d.includes("all in")) return { key: "allin", n, k: "allin" };
  if (d.startsWith("checks")) return { key: "check", n: "", k: "check" };
  if (d.startsWith("calls")) return { key: "call", n, k: "call" };
  if (d.startsWith("bets")) return { key: "bet", n, k: "bet" };
  if (d.startsWith("raises")) return { key: "raise", n, k: "raise" };
  return { key: "other", n: "", k: "other", raw: desc };
}

const CHIP_LABELS = {
  fold: ["Fold", "弃牌"], sb: ["SB", "小盲"], bb: ["BB", "大盲"],
  allin: ["All-in", "全下"], check: ["Check", "过牌"], call: ["Call", "跟注"],
  bet: ["Bet", "下注"], raise: ["Raise", "加注"],
};
function chipLabel(a) {
  if (a.key === "other") return a.raw || "";
  const pair = CHIP_LABELS[a.key];
  return (G.lang === "zh" ? pair[1] : pair[0]) + (a.n || "");
}

function resetSummary() {
  G.summary = { handNo: G.state ? G.state.hand_no : 0, lines: [], winners: {}, active: false };
  const el = $("summary");
  if (el) { el.classList.add("hidden"); el.innerHTML = ""; }
}

/* ------------------------- language switching ------------------------- */

function applyLang() {
  localStorage.setItem("holdem_lang", G.lang);
  document.documentElement.lang = G.lang === "zh" ? "zh-CN" : "en";
  document.title = t("page_title");
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.innerHTML = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  const sel = $("opt-lang");
  if (sel) sel.value = G.lang;
  $("btn-lang").textContent = G.lang === "zh" ? "EN" : "中文";
  // redraw everything language-dependent that's currently on screen
  if (G.state) render();
  if (G.mode === "action") showActionControls();
  else if (G.mode === "between") showBetweenControls(G.lastAllowance);
}

$("opt-lang").addEventListener("change", () => { G.lang = $("opt-lang").value; applyLang(); });
$("btn-lang").addEventListener("click", () => { G.lang = G.lang === "zh" ? "en" : "zh"; applyLang(); });

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
    language: G.lang,          // what the agents speak
  };
  if (G.accessCode) options.access_code = G.accessCode;
  $("setup-note").textContent = t("shuffling");
  fetch("/api/new", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  })
    .then((r) => {
      if (r.status === 403) {          // host set an access code — ask and retry
        const code = prompt(t("access_prompt"));
        if (code) { G.accessCode = code; startGame(); }
        else $("setup-note").textContent = t("access_required");
        return null;
      }
      return r.json();
    })
    .then((data) => {
      if (!data) return;               // 403 branch handled it
      if (!data.sid) {
        $("setup-note").textContent = data.error || t("start_failed");
        return;
      }
      G.sid = data.sid;
      $("setup").classList.add("hidden");
      $("game").classList.remove("hidden");
      connect();
    })
    .catch(() => { $("setup-note").textContent = t("start_failed"); });
}

function clampInt(v, lo, hi, dflt) {
  const n = parseInt(v, 10);
  if (isNaN(n)) return dflt;
  return Math.max(lo, Math.min(hi, n));
}

/* ------------------------- SSE stream ------------------------- */

function connect() {
  G.es = new EventSource("/api/events?sid=" + G.sid);
  G.es.onmessage = (e) => {
    let ev;
    try { ev = JSON.parse(e.data); } catch (_) { return; }
    handle(ev);
  };
  G.es.onerror = () => { /* EventSource auto-reconnects; server re-syncs. */ };
}

function heroName() { return G.state ? G.state.hero_name : null; }

function handle(ev) {
  if (ev.state) G.state = ev.state;

  switch (ev.type) {
    case "start":
      G.meta = ev.meta || {};
      if (G.lang === "zh")
        feed(G.meta.offline ? t("note_offline") : t("note_online", { model: G.meta.model }), "sys");
      else if (G.meta.note) feed(G.meta.note, "sys");
      break;
    case "hand_start":
      clearBubbles(); hideAward();
      resetSummary();
      G.actions = {};
      G.thinking = null;
      feed(t("feed_hand", { n: ev.hand_no, sb: ev.sb, bb: ev.bb, dealer: esc(ev.dealer) }), "sys");
      break;
    case "street":
      G.actions = {};   // fresh street — clear last-move chips
      feed(trStreet(ev.street), "sys");
      break;
    case "action":
      G.thinking = null;
      G.actions[ev.name] = actionLabel(ev.desc);
      feed(`<span class="who">${esc(ev.name)}</span> ${esc(trActionDesc(ev.desc))}${G.lang === "zh" ? "。" : "."}`);
      break;
    case "thinking":
      G.thinking = ev.name;
      break;
    case "chat":
      if (ev.name === G.thinking) G.thinking = null;  // their reply arrived
      showBubble(ev.name, ev.text, ev.to);
      feed(`<span class="who">${esc(ev.name)}</span>${ev.to ? esc(t("to_x", { x: ev.to })) : ""}: "${esc(ev.text)}"`, "chat");
      if (typeof speak === "function" && ev.name !== heroName()) speak(ev.name, ev.text);
      break;
    case "reveal":
      feed(t("allin_reveal"), "sys");
      break;
    case "showdown":
      (ev.players || []).forEach((p) =>
        feed(`<span class="who">${esc(p.name)}</span> ${t("shows")} ${cardsText(p.cards)} — ${esc(trHand(p.hand))}`));
      break;
    case "peek":
      (ev.players || []).forEach((p) =>
        feed(`<span class="who">${esc(p.name)}</span> ${t("had")} ${cardsText(p.cards)}${p.folded ? t("folded_paren") : ""}${p.hand ? " — " + esc(trHand(p.hand)) : ""}`, "sys"));
      break;
    case "pot_award":
      feed(esc(trPot(ev.text)), "pot");
      recordAward(ev.text);   // parse the raw English shape; display is translated
      break;
    case "buy":
      feed(`<span class="who">${esc(ev.name)}</span> ${t("feed_buy", { amount: ev.amount, debt: ev.debt })}`, "sys");
      break;
    case "rebuy":
      feed(`<span class="who">${esc(ev.name)}</span> ${t("feed_felted", { stake: ev.stake, debt: ev.debt })}`, "sys");
      if (ev.line) {
        showBubble(ev.name, ev.line, null);
        if (typeof speak === "function") speak(ev.name, ev.line);
      }
      break;
    case "standings":
      renderStandings(ev);
      break;
    case "await":
      onAwait(ev);
      break;
    case "log":
      if (ev.text) feed(esc(ev.text), ev.level === "warn" || ev.level === "error" ? "warn" : "sys");
      break;
    case "game_over":
      onGameOver();
      break;
    case "fatal":
      $("setup").classList.remove("hidden");
      $("game").classList.add("hidden");
      $("setup-note").textContent = ev.text || t("start_failed");
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
    feed(esc(ev.prompt || "…"), "sys");
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
    callBtn.textContent = t("check");
  } else if (toCall >= heroStack) {
    callBtn.textContent = t("call_allin", { n: heroStack });
  } else {
    callBtn.textContent = t("call_n", { n: toCall });
  }

  $("act-raise").classList.toggle("hidden", !L.can_raise);
  $("raise-panel").classList.add("hidden");

  const hint = L.hero_hand_hint ? t("you_have", { hand: trHand(L.hero_hand_hint) }) : t("your_move");
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
  fetch("/api/input?sid=" + G.sid, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ line }),
  }).catch(() => {});
}

/* between hands */
function showBetweenControls(allowance) {
  setControls("between");
  G.lastAllowance = allowance;
  const buy = $("buy-amount");
  buy.max = allowance; buy.value = 0;
  buy.disabled = allowance <= 0;
  $("buy-go").disabled = allowance <= 0;
  $("buy-allow").textContent = allowance > 0 ? t("buy_upto", { n: allowance }) : t("buy_max");
  $("hero-hint").textContent = t("hand_over");
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
  const txt = $("say-input").value.trim();
  if (!txt) return;
  $("say-input").value = "";
  postInput(G.mode === "text" ? txt : "say " + txt);
  if (G.mode === "text") G.mode = null;
}

function leaveTable() {
  if (!G.sid) return;
  fetch("/api/quit?sid=" + G.sid, { method: "POST" }).catch(() => {});
}

function onGameOver() {
  if (G.es) { G.es.close(); G.es = null; }
  setControls("none");
  $("hero-hint").textContent = "";
  $("mode-label").textContent = t("mode_over");
  showAward(t("game_over_msg"));
}

/* ------------------------- rendering ------------------------- */

function render() {
  const s = G.state;
  if (!s) return;

  // top bar
  $("hand-label").textContent = s.hand_no ? t("hand_no", { n: s.hand_no }) : "—";
  $("blinds-label").textContent = t("blinds", { sb: s.sb, bb: s.bb });
  const ml = $("mode-label");
  if (s.live) { ml.textContent = trStreet(s.street) || t("in_play"); ml.classList.add("live"); }
  else { ml.textContent = t("between_hands"); ml.classList.remove("live"); }

  // pot + street tag + board
  const pot = $("pot");
  if (s.live && s.pot > 0) { pot.classList.remove("hidden"); $("pot-amt").textContent = s.pot; }
  else pot.classList.add("hidden");
  $("street-tag").textContent = s.live ? (trStreet(s.street) || "") : "";
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
    status = `<span class="badge think">${t("thinking")}</span>`;
  } else {
    let a = G.actions[seat.name];
    if (!a) {
      if (seat.folded) a = { key: "fold", n: "", k: "fold" };
      else if (seat.all_in) a = { key: "allin", n: "", k: "allin" };
    }
    if (a) status = `<span class="act-chip k-${a.k}">${esc(chipLabel(a))}</span>`;
  }
  body.innerHTML =
    `<div class="seat-name">${esc(seat.name)}</div>` +
    `<div class="seat-stack">$${seat.stack}</div>` +
    (seat.debt ? `<div class="seat-debt">${G.lang === "zh" ? "记账 " + seat.debt : "tab " + seat.debt}</div>` : "") +
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

// The pot-award lines are worded by the engine (always in English — display is
// translated separately); pull the winner(s) + amount out so we can glow the
// seats and stack a "+chips" badge on them. If a line doesn't parse we still
// show its text — nothing is lost.
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
    `<div class="sum-title">${t("sum_title", { n: G.summary.handNo })}</div>` +
    G.summary.lines.map((l) => `<div class="sum-line">🏆 ${esc(trPot(l))}</div>`).join("");
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
    const tab = r.debt ? t("tab_net", { debt: r.debt, net: net }) : "";
    return `${r.is_human ? "★ " : ""}${esc(r.name)} — $${r.stack}${esc(tab)}`;
  });
  feed(`<b>${esc(trTitle(ev.title))}:</b><br>` + rows.join("<br>"), "sys");
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

/* apply the saved/browser language on load */
applyLang();
