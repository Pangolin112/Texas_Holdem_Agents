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
    lbl_difficulty: "AI difficulty",
    diff_casual: "Casual — they play by feel",
    diff_standard: "Standard",
    diff_shark: "Shark — they remember and exploit",
    lbl_coach_style: "Coach style",
    cs_beginner: "Beginner — explains every term",
    cs_standard: "Standard",
    cs_pro: "Pro — ranges and sizing",
    tab_table: "Table", tab_side: "Odds · Coach", tab_feed: "Feed",
    chk_offline: "Offline (built-in bots, no API)",
    chk_peek: "Peek mode (reveal cards after each hand)",
    chk_odds: "Show my live hand strength and win odds",
    chk_coach: "AI coach: read the table and tell me what to do",
    chk_fast: "Fast-forward the hand after I fold",
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
    hint_odds: " · you win {p}",
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
    note_online: "Opponents powered by {provider} model: {model} (auto-fallback if unavailable).",
    tab_net: " · tab {debt} · net {net}",
    heard: "heard",
    help_title: "How to play",
    help_1: "<b>Fold / Check / Call</b> — the middle button knows whether you can check for free or must call.",
    help_2: "<b>Raise</b> — opens a slider; drag it or use the ½·¾·pot shortcuts, then Confirm.",
    help_3: "<b>All-in</b> — shove your whole stack.",
    help_4: "<b>Say</b> — talk to the table at any moment, even while someone is thinking; they hear you right away. Name someone and they answer; ask <i>why</i> they made a move and they'll explain their real reasoning.",
    help_5: "<b>Voice</b> — click 🎤 and speak: \"fold\", \"call\", \"raise to 200\", \"all in\" play the move; anything else is table talk. With 🔊 on, the agents answer out loud in their own natural voices.",
    help_6: "<b>Between hands</b> — buy more chips (added to your tab) or deal the next hand.",
    help_7: "<b>Autopilot</b> — commit to a move before the turn reaches you: fold in advance, call everything, or call just this street. It clears when the hand ends.",
    help_8: "<b>Your hand</b> — the panel on the right tracks your best five cards live, and how often each hand you can still make actually wins. When the hand ends you get every seat's cards, strongest first.",
    help_note: "A player can bluff about their cards, but if they announce a move (\"I fold\", \"I'm all in\") the game forces the move to match.",
    got_it: "Got it",
    /* autopilot */
    auto_label: "Autopilot",
    auto_fold: "Fold in advance",
    auto_call: "Call everything",
    auto_street: "Call this street",
    auto_on_auto_fold: "armed — folding to any bet this hand (click again to cancel)",
    auto_on_auto_call: "armed — calling everything this hand (click again to cancel)",
    auto_on_auto_call_street: "armed — calling for the rest of this street (click again to cancel)",
    /* live hand + odds panel */
    adv_title: "Your hand",
    adv_preflop: "Preflop — no board yet",
    adv_make: "make",
    adv_win: "win",
    adv_total: "you win",
    adv_samples: "{n} hands simulated vs {k} live",
    adv_final: "{n} hands simulated vs {k} live · board complete",
    adv_folded: "You're out of this hand.",
    /* finished-hand review */
    res_title: "Hand #{n} — final hands, strongest first",
    res_mucked: "mucked — not shown",
    res_folded: "folded",
    res_note: "Mucked hands stay secret. Tick “Peek mode” at setup to see folded players' cards too.",
    res_preflop: "no board — the hand ended before the flop",
    /* the coach */
    coach_title: "AI Coach",
    coach_thinking: "reading the table…",
    coach_sure: "{p} sure",
    coach_math: "you win {e} vs random · {a} vs their range · the price needs {o}",
    coach_math_free: "you win {e} vs random · {a} vs their range · nothing to call",
    coach_bluff: "bluffing {p}",
    bucket_strong: "strong", bucket_medium: "medium", bucket_draw: "draws",
    bucket_weak: "weak", bucket_air: "air",
    danger_0: "all clear", danger_1: "looking good", danger_2: "close spot",
    danger_3: "danger", danger_4: "serious danger",
    /* the debrief */
    rr_title: "The coach's debrief",
    rr_told: "told", rr_ok: "✓ fine", rr_net: "this hand {n}",
    just_call: "Call",
    grade_scared_fold: "scared fold — the price was right",
    grade_loose_call: "loose call — you were priced out",
    grade_wild_raise: "raised while behind",
    grade_missed_value: "missed value — a bet was owed",
    leak_scared_fold: "scared folds", leak_loose_call: "loose calls",
    leak_wild_raise: "wild raises", leak_missed_value: "missed value",
    rr_session: "{h} hands · followed {f}/{d} · net {nf} listening, {nd} your own way",
    rr_leaks: "leaks: {list}",
    /* the send-off */
    fw_title: "The coach walks you out",
    fw_again: "Sit back down",
    fw_hands: "{n} hands played", fw_net: "net {n}",
    fw_follow: "followed the coach {f}/{d}",
    fw_split: "{nf} listening · {nd} your own way",
    follow_ai: "Follow the coach",
    auto_coach: "Follow the coach this street",
    auto_on_auto_advisor: "armed — doing whatever the coach says this street (click again to cancel)",
    raise_to_n: "Raise to {n}",
    read_shoved: "all-in — the nuts or nothing",
    read_polarized: "huge bet — monster or air",
    read_strong: "raising hard — big pairs, sets, made hands",
    read_aggressive: "raised — better than average",
    read_calling: "just calling — draws, medium pairs",
    read_passive: "checking along — likely weak",
    read_quiet: "nothing to read yet",
  },
  zh: {
    page_title: "德州扑克 — 你 vs 机器",
    title_sub: "无限注德州扑克",
    tagline: "你，对阵一桌 AI 老牌友。",
    lbl_name: "你的名字", lbl_lang: "Language / 语言", lbl_opponents: "对手数量",
    lbl_stack: "起始筹码", lbl_sb: "小盲注", lbl_bb: "大盲注",
    lbl_model: "模型",
    lbl_difficulty: "AI 水平",
    diff_casual: "休闲——凭感觉打",
    diff_standard: "标准",
    diff_shark: "鲨鱼——记住并针对你的打法",
    lbl_coach_style: "教练风格",
    cs_beginner: "新手——每个术语都解释",
    cs_standard: "标准",
    cs_pro: "老手——聊范围和下注尺度",
    tab_table: "牌桌", tab_side: "胜率·教练", tab_feed: "动态",
    chk_offline: "离线模式（内置机器人，不调用 API）",
    chk_peek: "偷看模式（每手结束后亮出所有底牌）",
    chk_odds: "显示我的实时牌力与胜率",
    chk_coach: "AI 教练：帮我读牌桌，告诉我该怎么打",
    chk_fast: "我弃牌后快进——AI 秒下,直奔下一手",
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
    hint_odds: " · 胜率 {p}",
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
    note_online: "对手由 {provider} 模型驱动：{model}（不可用时自动降级）。",
    tab_net: " · 记账 {debt} · 净值 {net}",
    heard: "听到",
    help_title: "怎么玩",
    help_1: "<b>弃牌 / 过牌 / 跟注</b> —— 中间的按钮会自动判断你能免费过牌还是必须跟注。",
    help_2: "<b>加注</b> —— 打开滑块；拖动它或用 半池·¾池·一池 快捷键，然后点确定。",
    help_3: "<b>全下</b> —— 推入你的全部筹码。",
    help_4: "<b>说话</b> —— 任何时刻都能和牌桌聊天，哪怕有人正在思考，他们也立刻听得见。点名谁，谁就会回答；问他们<i>为什么</i>那么打，他们会解释真实的思路。",
    help_5: "<b>语音</b> —— 点 🎤 开口说：“弃牌”“跟注”“加注到 200”“全下”会直接出牌；说别的就是牌桌聊天。开着 🔊，对手们会用各自自然的嗓音开口回话。",
    help_6: "<b>两手之间</b> —— 买更多筹码（记在账上）或发下一手。",
    help_7: "<b>自动</b> —— 还没轮到你，就可以先把这一手的决定定下来：预先弃牌、默认全跟、或者只跟当前这一轮。这手打完就自动解除。",
    help_8: "<b>我的牌</b> —— 右边的面板实时显示你当前的最大牌型和用到的五张牌，并算出你还能凹成的每种牌型各有多大概率、各能赢多少。这手结束后，会按牌力从强到弱列出每家的牌。",
    help_note: "玩家可以在牌上虚张声势，但只要嘴上宣布了动作（“我弃了”“我全下”），游戏会强制动作和话一致。",
    got_it: "明白",
    /* autopilot */
    auto_label: "自动",
    auto_fold: "预先弃牌",
    auto_call: "默认全跟",
    auto_street: "跟当前轮次",
    auto_on_auto_fold: "已预约：本手只要有人下注就弃牌（再点一次取消）",
    auto_on_auto_call: "已预约：本手一路跟到底（再点一次取消）",
    auto_on_auto_call_street: "已预约：本轮剩下的下注都跟（再点一次取消）",
    /* live hand + odds panel */
    adv_title: "我的牌",
    adv_preflop: "翻牌前——公共牌还没发",
    adv_make: "成牌",
    adv_win: "赢率",
    adv_total: "你的胜率",
    adv_samples: "模拟 {n} 手 · 对 {k} 家",
    adv_final: "模拟 {n} 手 · 对 {k} 家 · 公共牌已发完",
    adv_folded: "你这手已经弃牌了。",
    /* finished-hand review */
    res_title: "第 {n} 手 · 各家最终牌型（由强到弱）",
    res_mucked: "盖牌，未亮出",
    res_folded: "已弃牌",
    res_note: "盖掉的牌不会公开。在开局设置里勾选“偷看模式”，弃牌玩家的底牌也会一起亮出来。",
    res_preflop: "翻牌前就结束了，没有公共牌",
    /* the coach */
    coach_title: "AI 教练",
    coach_thinking: "正在读牌桌……",
    coach_sure: "把握 {p}",
    coach_math: "对随机牌胜率 {e} · 对他们的范围 {a} · 这个价格需要 {o}",
    coach_math_free: "对随机牌胜率 {e} · 对他们的范围 {a} · 不用跟注",
    coach_bluff: "诈唬 {p}",
    bucket_strong: "成牌", bucket_medium: "中等", bucket_draw: "听牌",
    bucket_weak: "很弱", bucket_air: "空气",
    danger_0: "安全", danger_1: "占优", danger_2: "胶着",
    danger_3: "危险", danger_4: "高危",
    /* the debrief */
    rr_title: "AI 教练复盘",
    rr_told: "建议", rr_ok: "✓ 没毛病", rr_net: "本手净 {n}",
    just_call: "跟注",
    grade_scared_fold: "怂弃——价格明明合适",
    grade_loose_call: "松跟——这个价不值",
    grade_wild_raise: "落后还加注",
    grade_missed_value: "错过价值——该下注的",
    leak_scared_fold: "怂弃", leak_loose_call: "松跟",
    leak_wild_raise: "乱加注", leak_missed_value: "漏价值",
    rr_session: "共 {h} 手 · 听劝 {f}/{d} · 听劝净 {nf} · 自己打净 {nd}",
    rr_leaks: "漏洞:{list}",
    /* the send-off */
    fw_title: "散场陈词",
    fw_again: "再坐下来",
    fw_hands: "共打了 {n} 手", fw_net: "净胜负 {n}",
    fw_follow: "听劝 {f}/{d}",
    fw_split: "听劝净 {nf} · 自己打净 {nd}",
    follow_ai: "遵循 AI",
    auto_coach: "本轮跟随 AI",
    auto_on_auto_advisor: "已预约：本轮听教练的（再点一次取消）",
    raise_to_n: "加注到 {n}",
    read_shoved: "全下——不是坚果就是空气",
    read_polarized: "巨额下注——大牌或者纯诈唬",
    read_strong: "连续加注——大对子、三条、成牌",
    read_aggressive: "加注过——比平均水平强",
    read_calling: "只是跟注——听牌或中等牌",
    read_passive: "一路过牌——大概率很弱",
    read_quiet: "还看不出什么",
  },
};

/* hand categories, keyed by the engine's category number (8 = straight flush) */
const CAT_ZH = { 8: "同花顺", 7: "四条", 6: "葫芦", 5: "同花", 4: "顺子",
                 3: "三条", 2: "两对", 1: "一对", 0: "高牌" };
function catName(row) {
  if (G.lang !== "zh") return row.name;
  return CAT_ZH[row.cat] !== undefined ? CAT_ZH[row.cat] : row.name;
}
function pct(x) { return Math.round(x * 100) + "%"; }

/* What you're holding, named: a real hand once there's a board, the preflop
 * shape before that. The engine sends the shape structured (pair/suited/
 * offsuit) rather than a phrase, so zh can say it its own way. */
function handLabel(made) {
  if (!made) return null;
  if (!made.preflop) return trHand(made.name);
  if (G.lang !== "zh") return made.name;
  const r = (made.cards || []).map((c) => c.rank);
  if (made.kind === "pair") return "口袋对 " + r[0];
  // Hyphenated: a ten makes "109不同花" unreadable without a separator.
  return r[0] + "-" + r[1] + (made.kind === "suited" ? " 同花" : " 不同花");
}

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
  // cards.plural() only ever appends "s" — "Sixes" is the one exception. A
  // blanket /es$/ strip turns Nines into "nin" and Aces into "ac", which then
  // fall through untranslated.
  const base = w === "sixes" ? "six" : w.replace(/s$/, "");
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
  odds: null,         // newest live read for our seat (null until one arrives)
  advice: null,       // the coach's call on the spot in front of us
  verdict: null,      // its word once the hand is over
  review: null,       // the debrief: decisions graded + session ledger
  result: null,       // finished-hand review: every seat's cards + formula
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
  if (G.result && !$("result").classList.contains("hidden")) showResult();
  if (G.mode === "action") showActionControls();
  else if (G.mode === "between") showBetweenControls(G.lastAllowance);
}

$("opt-lang").addEventListener("change", () => { G.lang = $("opt-lang").value; applyLang(); });
$("btn-lang").addEventListener("click", () => { G.lang = G.lang === "zh" ? "en" : "zh"; applyLang(); });

/* ---- table feed (left column) show/hide, remembered. The odds + coach
 * column on the right is always on — only the feed is optional. ---- */

function applyFeedVisible() {
  const on = localStorage.getItem("holdem_feed") !== "0";
  $("feed").classList.toggle("hidden", !on);
  $("btn-feed").classList.toggle("off", !on);
  const tab = document.querySelector('.mtab[data-target="feed"]');
  if (tab) tab.classList.toggle("hidden", !on);
}
$("btn-feed").addEventListener("click", () => {
  const on = localStorage.getItem("holdem_feed") !== "0";
  localStorage.setItem("holdem_feed", on ? "0" : "1");
  applyFeedVisible();
});
applyFeedVisible();

/* ---- mobile pager: on narrow screens the three columns become full-width
 * pages in a horizontal scroll-snap strip — swipe, or tap a tab. The tabs
 * mirror whichever page the strip has snapped to. ---- */

const PAGE_ORDER = ["table-wrap", "side", "feed"];   // visual (swipe) order

/* On the coach/feed pages the control bar gives its whole space to the
 * panels — your own turn is exactly when the coach's read matters most, so
 * the bar never covers it. The table page always has the buttons; swipe
 * back there to act. Desktop ignores all of this via the media query. */
function updateHeroBar() {
  $("hero-bar").classList.toggle(
    "off-table", (G.page || "table-wrap") !== "table-wrap");
}

function syncTabs() {
  const c = $("content");
  const w = c.clientWidth || 1;
  const vis = PAGE_ORDER.map($).filter((el) => el && !el.classList.contains("hidden"));
  if (!vis.length) return;
  const page = vis[Math.max(0, Math.min(Math.round(c.scrollLeft / w), vis.length - 1))];
  G.page = page.id;
  document.querySelectorAll(".mtab").forEach((b) => {
    b.classList.toggle("active", b.dataset.target === page.id);
  });
  updateHeroBar();
}
$("content").addEventListener("scroll", () => requestAnimationFrame(syncTabs));
window.addEventListener("resize", syncTabs);
document.querySelectorAll(".mtab").forEach((b) => {
  b.addEventListener("click", () => {
    const el = $(b.dataset.target);
    if (el) el.scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" });
  });
});

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
    difficulty: $("opt-difficulty").value,
    coach_style: $("opt-coach-style").value,
    offline: $("opt-offline").checked,
    show_cards: $("opt-showcards").checked,
    odds: $("opt-odds").checked,
    coach: $("opt-coach").checked,
    fast: $("opt-fast").checked,
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
      if (G.meta.offline) feed(t("note_offline"), "sys");
      else if (G.lang === "en" && G.meta.note) feed(G.meta.note, "sys");
      else feed(t("note_online", {
        provider: G.meta.provider || "OpenAI",
        model: G.meta.model || "",
      }), "sys");
      break;
    case "hand_start":
      clearBubbles(); hideAward();
      resetSummary();
      hideResult();
      // A new deal means neither bar applies until the engine asks again —
      // catches every path into a hand, not just the Next-hand click.
      if (G.mode !== "action") setControls(null);
      G.odds = null; G.result = null;
      G.advice = null; G.verdict = null; G.review = null;
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
    case "hand_result":
      G.result = ev;
      showResult();
      (ev.players || []).forEach((p) => {
        if (!p.known || !p.hand) return;
        feed(`<span class="who">${esc(p.name)}</span> ${t("had")} ${cardsText(p.cards)}` +
             `${p.folded ? t("folded_paren") : ""} — ${esc(trHand(p.hand))}`, "sys");
      });
      break;
    case "odds":
      G.odds = ev.odds;
      break;
    case "advice":
      G.advice = ev.advice;
      G.verdict = null;
      // The advice IS the coach's answer — it's done thinking. Nothing else
      // clears this (the events that clear a seat's flag are acting and
      // talking, and the coach does neither), so without this line the panel
      // sits on "reading the table…" through the player's whole turn.
      if (G.thinking === (G.meta.coach_name || "Coach")) G.thinking = null;
      break;
    case "advisor_line":     // you went your own way and it had something to say
    case "advisor_verdict":  // the hand is over and it found out if it was right
      G.verdict = { text: ev.text, tone: ev.tone || "defiance" };
      feed(`<span class="who">${esc(coachName())}</span>: "${esc(ev.text)}"`, "coach");
      if (typeof speak === "function") speak(G.meta.coach_name || "Coach", ev.text);
      break;
    case "hand_review":
      // The debrief lands moments after the result overlay opens (the coach
      // was writing it) — refresh the overlay so it slots in underneath.
      G.review = ev.review;
      if (ev.review && ev.review.text)
        feed(`<span class="who">${esc(coachName())}</span>: "${esc(ev.review.text)}"`, "coach");
      if (G.result && !$("result").classList.contains("hidden")) showResult();
      break;
    case "autopilot":
      // The snapshot carries the armed mode; this event just wakes the render.
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
    case "farewell":
      showFarewell(ev.farewell || {});
      break;
    case "game_over":
    case "closed":
      // "closed" is the server retiring the session (the Leave button, or an
      // old table being reaped) — ignoring it left the Leave button looking
      // dead: the game ended server-side and the page never noticed.
      onGameOver();
      break;
    case "fatal":
      $("setup").classList.remove("hidden");
      $("game").classList.add("hidden");
      $("setup-note").textContent = ev.text || t("start_failed");
      break;
    case "sync": case "ping": break;
  }

  render();
}

/* ------------------------- input requests ------------------------- */

function onAwait(ev) {
  G.mode = ev.mode;
  // An input request means the engine is blocked waiting on the human —
  // whatever was "thinking" has necessarily finished.
  G.thinking = null;
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
  $("hero-hint").textContent = heroHintText();
  renderFollowButton();
}

/* The follow button says what it will actually do, so it's never a leap of
 * faith — "Follow the coach · Raise to 156". */
function renderFollowButton() {
  const btn = $("act-follow");
  const a = G.advice;
  const show = !!(a && a.command && G.mode === "action" && G.meta.coach);
  btn.classList.toggle("hidden", !show);
  if (show) btn.textContent = t("follow_ai") + " · " + adviceText(a);
}

/* The line right above the buttons — what you hold and what it's worth. Reads
 * off the live snapshot rather than the turn's legal-move info, so it names the
 * preflop shape too, where there's no five-card hand to report. */
function heroHintText() {
  const s = G.state;
  const made = s && s.hero_hand;
  const label = handLabel(made);
  let txt = label ? t("you_have", { hand: label }) : t("your_move");
  if (G.odds && s && !s.hero_folded) {
    txt += t("hint_odds", { p: pct(G.odds.equity) });
  }
  return txt;
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

/* The move is made: lock the bar and shrink it back to one row — the open
 * raise panel would otherwise sit over the felt until the next turn. */
function lockControls() {
  G.mode = null; G.legal = null;
  $("controls").classList.add("disabled");
  $("raise-panel").classList.add("hidden");
  $("hero-hint").textContent = "";
}

/* action: send a command and lock controls until the next request */
function act(line) {
  if (!G.sid) return;
  postInput(line);
  lockControls();
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
  // Gone, not greyed: the bar has no business on screen while the next
  // hand is being dealt — it comes back with the next between-hands prompt.
  $("between").classList.add("disabled", "hidden");
  G.mode = null;
  postInput("");
});
$("buy-go").addEventListener("click", () => {
  const amt = clampInt($("buy-amount").value, 0, 1e9, 0);
  if (amt > 0) postInput("buy " + amt);
});

/* say box: table talk goes out-of-band (/api/say) so it works at ANY moment —
 * even while an opponent is thinking. A rare "text" prompt (e.g. a confirm)
 * still answers the engine's pending input directly. */
$("say-go").addEventListener("click", sendSay);
$("say-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendSay(); });
function sendSay() {
  const txt = $("say-input").value.trim();
  if (!txt) return;
  $("say-input").value = "";
  if (G.mode === "text") { postInput(txt); G.mode = null; return; }
  sendChat(txt);
}

function sendChat(text) {
  fetch("/api/say?sid=" + G.sid, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  }).catch(() => {});
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
  // The send-off overlay is the ceremony; the award banner is the fallback
  // for games that end without one (no coach, or a reaped session).
  if ($("farewell").classList.contains("hidden")) showAward(t("game_over_msg"));
}

/* ---- the send-off ---- */

function showFarewell(f) {
  hideResult();
  $("fw-text").textContent = f.text ? "“" + f.text + "”" : "";
  const s = f.session || {};
  const rows = [t("fw_hands", { n: f.hands || 0 }) + " · " +
                t("fw_net", { n: signed(f.net || 0) })];
  if (s.decisions) {
    rows.push(t("fw_follow", { f: s.followed, d: s.decisions }));
    rows.push(t("fw_split", { nf: signed(s.net_followed || 0),
                              nd: signed(s.net_defied || 0) }));
    const leaks = Object.entries(s.mistakes || {})
      .map(([k, n]) => t("leak_" + k) + "×" + n).join(" · ");
    if (leaks) rows.push(t("rr_leaks", { list: leaks }));
  }
  $("fw-stats").innerHTML = rows.map((r) => `<div>${esc(r)}</div>`).join("");
  $("farewell").classList.remove("hidden");
  if (f.text && typeof speak === "function") speak(G.meta.coach_name || "Coach", f.text);
}

$("fw-again").addEventListener("click", () => location.reload());

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
  // The felt shifts hue with the street (see style.css) — a second, ambient
  // way to feel where the hand is without reading the tag.
  $("table").dataset.street = s.live && s.street ? s.street : "";
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
  renderAdvisor();
  renderCoach();
  renderAutopilot();
  // Keep the hint live while it's our turn: the odds land after the prompt, and
  // the board can move under us when we're all-in.
  if (G.mode === "action") {
    $("hero-hint").textContent = heroHintText();
    renderFollowButton();
  }
}

/* ---- live read: best hand right now + what you can still get to ---- */

function heroSeat() {
  const s = G.state;
  return s && (s.seats || []).find((x) => x.is_human);
}

function renderAdvisor() {
  const el = $("advisor");
  const s = G.state;
  const hero = heroSeat();
  // Nothing to advise on before the deal, or when odds were switched off.
  if (!s || G.meta.odds === false || !hero || !hero.card_count) {
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");

  // The made hand comes off the snapshot, so it re-reads on every event —
  // the moment a card lands, not just when the odds finish simulating.
  const made = s.hero_hand;
  $("adv-made").textContent = made ? handLabel(made) : t("adv_preflop");
  const cards = made ? made.cards : (hero.cards || []);
  $("adv-cards").innerHTML = cards.map((c) => cardHTML(c, "mini")).join("");

  const o = G.odds;
  if (!o || s.hero_folded) {
    $("adv-equity").textContent = "";
    $("adv-rows").innerHTML = "";
    $("adv-note").textContent = s.hero_folded ? t("adv_folded") : "";
    return;
  }
  $("adv-equity").textContent = pct(o.equity);
  const legend =
    `<div class="adv-row legend"><span class="adv-cat"></span>` +
    `<span class="adv-num">${t("adv_make")}</span><span class="adv-bar"></span>` +
    `<span class="adv-num">${t("adv_win")}</span></div>`;
  const rows = (o.categories || [])
    // A category you touch once in a thousand runouts is noise, not a plan.
    .filter((c) => c.make >= 0.005)
    .map((c) => {
      const now = made && made.cat === c.cat ? " now" : "";
      return `<div class="adv-row${now}">` +
        `<span class="adv-cat">${esc(catName(c))}</span>` +
        `<span class="adv-num">${pct(c.make)}</span>` +
        `<span class="adv-bar"><i style="width:${Math.min(100, c.win * 100)}%"></i></span>` +
        `<span class="adv-num win">${pct(c.win)}</span></div>`;
    }).join("");
  const total =
    `<div class="adv-row total"><span class="adv-cat">${t("adv_total")}</span>` +
    `<span class="adv-num"></span><span class="adv-bar"></span>` +
    `<span class="adv-num win">${pct(o.equity)}</span></div>`;
  $("adv-rows").innerHTML = legend + rows + total;
  $("adv-note").textContent = t(o.final ? "adv_final" : "adv_samples",
                                { n: o.samples, k: o.opponents });
}

/* ---- the coach: the read, the call, and the word afterwards ---- */

function coachName() { return t("coach_title"); }

/* what the coach's recommendation is, in words — also the follow button's label */
function adviceText(a) {
  if (!a) return "";
  if (a.action === "fold") return t("fold");
  if (a.action === "check") return t("check");
  if (a.action === "all_in") return t("allin");
  if (a.action === "raise") return t("raise_to_n", { n: a.amount });
  return t("call_n", { n: a.to_call });
}

function readText(r) {
  // The model writes its own read in the table's language when it has one;
  // otherwise the structured key gets worded here.
  return r.note || t("read_" + r.key);
}

/* What his range is made of, as one stacked bar. The segments are a partition
 * of every hand he can hold, so the bar is always exactly full. */
function rangeBar(r) {
  if (!r.buckets || !r.buckets.length) return "";
  const segs = r.buckets.map((b) =>
    `<i class="b-${esc(b.key)}" style="width:${(b.p * 100).toFixed(1)}%" ` +
    `title="${esc(t("bucket_" + b.key))} ${pct(b.p)}"></i>`).join("");
  const keys = r.buckets.filter((b) => b.p >= 0.08).map((b) =>
    `<span class="k-${esc(b.key)}">${esc(t("bucket_" + b.key))} ${pct(b.p)}</span>`).join("");
  return `<div class="range-bar">${segs}</div><div class="range-keys">${keys}</div>`;
}

function renderCoach() {
  const el = $("coach");
  const s = G.state;
  if (!s || !G.meta.coach || !heroSeat() || !heroSeat().card_count) {
    el.className = "coach hidden";
    return;
  }

  const v = $("coach-verdict");
  if (G.verdict) {
    v.className = "coach-verdict tone-" + G.verdict.tone;
    v.textContent = "“" + G.verdict.text + "”";
  } else {
    v.className = "coach-verdict hidden";
  }

  const thinking = G.thinking && G.thinking === G.meta.coach_name;
  const a = G.advice;
  const body = $("coach-body");
  const chip = $("coach-danger");
  // Once the hand is over the verdict is the whole story — leaving the call it
  // made three streets ago on screen just reads as advice for a hand that no
  // longer exists. (A defiance line lands mid-hand, so it keeps the body.)
  const handOver = G.verdict && G.verdict.tone !== "defiance";
  if (!a || s.hero_folded || handOver) {
    body.classList.add("hidden");
    chip.className = "coach-danger hidden";
    el.className = "coach" + (thinking && !handOver && !s.hero_folded ? " analyzing" : "");
    $("coach-conf").textContent = thinking ? t("coach_thinking") : "";
    return;
  }
  body.classList.remove("hidden");
  // The panel wears the spot's danger color, white -> green -> blue -> red ->
  // purple. While the coach re-reads, the "analyzing" pulse sits on top; the
  // moment the new advice lands (thinking clears with it) the pulse drops and
  // the tint snaps — that flip IS the "analysis done" signal.
  const d = (a.danger === undefined || a.danger === null) ? 2 : a.danger;
  el.className = "coach d" + d + (thinking ? " analyzing" : "");
  chip.className = "coach-danger";
  chip.textContent = t("danger_" + d);
  $("coach-conf").textContent = thinking
    ? t("coach_thinking")
    : t("coach_sure", { p: pct(a.confidence) });

  $("coach-rec").innerHTML =
    `<span class="rec-verb k-${esc(a.action)}">${esc(adviceText(a))}</span>`;
  $("coach-line").textContent = a.line || "";
  $("coach-why").textContent = a.reasoning || "";
  $("coach-why").classList.toggle("hidden", !a.reasoning);
  // Name and bar on one line, then the read, then what his range is actually
  // made of. This is the range call, so it wraps in full rather than truncating.
  $("coach-reads").innerHTML = (a.reads || []).map((r) => {
    const bluff = r.bluff === null || r.bluff === undefined ? ""
      : `<span class="read-bluff">${t("coach_bluff", { p: pct(r.bluff) })}</span>`;
    return `<div class="read-row">` +
      `<div class="read-top">` +
        `<span class="read-name">${esc(r.name)}</span>${bluff}` +
        `<span class="read-bar"><i style="width:${Math.round(r.strength * 100)}%"></i></span>` +
      `</div>` +
      `<div class="read-note">${esc(readText(r))}</div>` +
      rangeBar(r) +
    `</div>`;
  }).join("");
  $("coach-math").textContent = a.to_call > 0
    ? t("coach_math", { e: pct(a.equity), a: pct(a.adjusted), o: pct(a.pot_odds) })
    : t("coach_math_free", { e: pct(a.equity), a: pct(a.adjusted) });
}

/* one click, exactly the move the coach asked for — the engine ships the
 * command with the advice so every front-end follows it the same way */
$("act-follow").addEventListener("click", () => {
  if (!G.advice || !G.advice.command) return;
  act(G.advice.command);
});

/* ---- autopilot: commit to a move before the turn gets to you ---- */

function renderAutopilot() {
  const s = G.state;
  const hero = heroSeat();
  const el = $("autopilot");
  const usable = !!(s && s.live && hero && hero.card_count &&
                    !s.hero_folded && !hero.all_in);
  el.classList.toggle("hidden", !usable);
  if (!usable) return;
  const mode = s.hero_auto;   // the engine's own state, never a local guess
  document.querySelectorAll(".auto-btn").forEach((b) => {
    b.classList.toggle("armed", b.dataset.mode === mode);
  });
  $("auto-state").textContent = mode ? t("auto_on_" + mode) : "";
}

document.querySelectorAll(".auto-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (!G.sid) return;
    const armed = G.state ? G.state.hero_auto : null;
    const mode = btn.dataset.mode === armed ? null : btn.dataset.mode;
    // If the turn is already ours, the server settles the move right away —
    // lock the controls now so the same move can't also be clicked manually.
    if (mode && G.mode === "action") {
      lockControls();
    }
    fetch("/api/auto?sid=" + G.sid, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }).catch(() => {});
  });
});

/* ---- finished-hand review ---- */

function showResult() {
  const r = G.result;
  if (!r) return;
  $("result-title").textContent = t("res_title", { n: r.hand_no });
  $("result-board").innerHTML = (r.board || []).length
    ? (r.board || []).map((c) => cardHTML(c, "mini")).join("")
    : `<span class="dim">${t("res_preflop")}</span>`;
  $("result-rows").innerHTML = (r.players || []).map(resultRow).join("");
  renderReview();
  $("result-note").textContent =
    (r.players || []).some((p) => !p.known) ? t("res_note") : "";
  $("result").classList.remove("hidden");
}

/* ---- the coach's debrief, under the result table ---- */

function advisedLabel(a) {
  if (!a) return "";
  if (a.action === "raise" && a.amount) return t("raise_to_n", { n: a.amount });
  return { fold: t("fold"), check: t("check"), call: t("just_call"),
           all_in: t("allin") }[a.action] || a.action;
}

function signed(n) { return (n >= 0 ? "+" : "") + n; }

function renderReview() {
  const el = $("result-review");
  const r = G.review;
  if (!r || r.hand_no !== (G.result && G.result.hand_no)) {
    el.className = "result-review hidden";
    el.innerHTML = "";
    return;
  }
  const rows = (r.decisions || []).map((d) => {
    const grade = d.grade
      ? `<span class="rr-grade">${esc(t("grade_" + d.grade))}</span>`
      : `<span class="rr-fine">${esc(t("rr_ok"))}</span>`;
    return `<div class="rr-row">` +
      `<span class="rr-street">${esc(trStreet(d.street))}</span>` +
      `<span class="rr-advised">${esc(t("rr_told"))} ${esc(advisedLabel(d.advised))}</span>` +
      `<span class="rr-did">${esc(trActionDesc(d.did))}</span>${grade}</div>`;
  }).join("");
  const s = r.session || {};
  const leaks = Object.entries(s.mistakes || {})
    .map(([k, n]) => t("leak_" + k) + "×" + n).join(" · ");
  const session = t("rr_session", {
    h: s.hands, f: s.followed, d: s.decisions,
    nf: signed(s.net_followed || 0), nd: signed(s.net_defied || 0),
  }) + (leaks ? " · " + t("rr_leaks", { list: leaks }) : "");
  el.className = "result-review";
  el.innerHTML =
    `<div class="rr-head"><span>${esc(t("rr_title"))}</span>` +
    `<span class="rr-net">${esc(t("rr_net", { n: signed(r.net) }))}</span></div>` +
    rows +
    (r.text ? `<div class="rr-text">“${esc(r.text)}”</div>` : "") +
    `<div class="rr-session">${esc(session)}</div>`;
}

function hideResult() { $("result").classList.add("hidden"); }

function resultRow(p, i) {
  const name = `<span class="res-name${p.is_human ? " you" : ""}">${esc(p.name)}</span>`;
  if (!p.known) {
    return `<div class="res-row muck"><span class="res-place"></span>${name}` +
      `<span class="res-hole">${cardHTML(null, "mini")}${cardHTML(null, "mini")}</span>` +
      `<span class="res-hand dim">${t("res_mucked")}</span>` +
      `<span class="res-five"></span><span class="res-won"></span></div>`;
  }
  const hole = (p.cards || []).map((c) => cardHTML(c, "mini")).join("");
  // In the five that played, ring the ones that came out of their hand — that's
  // the difference between a hand they made and a board everyone shares.
  const mine = new Set((p.cards || []).map((c) => c.code));
  const five = (p.best5 || [])
    .map((c) => cardHTML(c, "mini" + (mine.has(c.code) ? " own" : ""))).join("");
  const tag = p.won ? `<span class="res-win">+${p.won}</span>`
                    : (p.folded ? `<span class="dim">${t("res_folded")}</span>` : "");
  return `<div class="res-row${p.folded ? " folded" : ""}${p.won ? " won" : ""}">` +
    `<span class="res-place">#${i + 1}</span>${name}` +
    `<span class="res-hole">${hole}</span>` +
    `<span class="res-hand">${p.hand ? esc(trHand(p.hand)) : "—"}</span>` +
    `<span class="res-five">${five}</span>` +
    `<span class="res-won">${tag}</span></div>`;
}

$("result-close").addEventListener("click", hideResult);
$("result").addEventListener("click", (e) => {
  if (e.target.id === "result") hideResult();  // click the backdrop to dismiss
});

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

/* Same card as cardEl, as an HTML string — for the panels that build a whole
 * list in one go. Pass c = null for a face-down card. Mini cards hide their
 * corners in CSS, so rank + pip is the whole card. */
function cardHTML(c, extra) {
  const cls = "card " + (extra || "");
  if (!c) return `<div class="${cls} back"></div>`;
  return `<div class="${cls}${c.red ? " red" : ""}">` +
    `<div class="rank">${c.rank}</div><div class="pip">${c.symbol}</div></div>`;
}

/* speech bubbles anchored to a seat — above it normally, but a top-row seat
 * hangs its bubble BELOW instead: above would poke out of the table, and the
 * mobile pager clips overflow, swallowing the line entirely. */
function showBubble(name, text, to) {
  const pos = G.seatPos[name];
  if (!pos) return;
  const table = $("table");
  const old = table.querySelector(`.bubble[data-seat="${cssEsc(name)}"]`);
  if (old) old.remove();
  const b = document.createElement("div");
  const below = pos.y < 30;
  b.className = "bubble" + (below ? " below" : "");
  b.dataset.seat = name;
  b.style.left = Math.max(12, Math.min(88, pos.x)) + "%";
  b.style.top = (below ? pos.y + 9 : pos.y - 9) + "%";
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

function loadConfig() {
  return fetch("/api/config")
    .then((r) => r.json())
    .then((cfg) => {
      G.config = cfg;
      const inp = $("opt-model");
      if (inp && cfg.model) {
        inp.value = cfg.model;
        inp.placeholder = cfg.model;
      }
      const dl = $("model-suggestions");
      if (dl && cfg.model_suggestions) {
        dl.innerHTML = cfg.model_suggestions
          .map((m) => `<option value="${esc(m)}">`)
          .join("");
      }
    })
    .catch(() => {});
}

/* apply the saved/browser language on load */
loadConfig().then(applyLang);
