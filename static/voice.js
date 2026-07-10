/* ===================== Texas Hold'em — voice in/out =====================
 * Loaded after app.js; shares its globals (G, t, act, postInput, sendChat,
 * feed, esc).
 *
 * OUT — the agents speak with natural voices: each opponent line is sent to
 *   the server's /api/tts, which proxies OpenAI's speech API (the key never
 *   reaches the browser) with a per-personality voice and delivery style.
 *   Only the words are spoken — never the speaker's name. Offline games (or
 *   a TTS hiccup) fall back to the browser's built-in speechSynthesis.
 *   Toggle with the 🔊 button.
 *
 * IN — you speak: the 🎤 button uses the Web Speech API (Chrome/Edge; needs
 *   HTTPS or localhost). On your turn, "fold", "call", "check", "raise to
 *   200", "all in" — or 弃牌 / 跟注 / 过牌 / 加注到200 / 全下 — play the move
 *   directly; anything else is table talk, delivered instantly whatever the
 *   game is doing (even mid-thinking), exactly like the Say box.
 *   Between hands: "next hand" / 下一手 deals, "buy 200" / 买200 tops up.
 * ======================================================================= */

const Voice = {
  ttsOn: localStorage.getItem("holdem_tts") !== "0",
  queue: [],           // spoken lines waiting their turn (one at a time)
  playing: false,
  rec: null,
  listening: false,
};

// Playback speed for the agents' voices (browsers pitch-correct, so faster
// stays natural). Applies to both the OpenAI audio and the fallback voice.
const SPEECH_RATE = 1.3;

function voiceLang() { return G.lang === "zh" ? "zh-CN" : "en-US"; }

/* ------------------------- output: agents talk ------------------------- */

/* app.js calls speak(name, text) for every opponent chat line. The name only
 * selects the voice — it is never spoken aloud. */
function speak(name, text) {
  if (!Voice.ttsOn) return;
  if (Voice.queue.length >= 3) return;   // table's chatty — don't build a backlog
  Voice.queue.push({ name, text });
  pumpSpeech();
}

function pumpSpeech() {
  if (Voice.playing || !Voice.queue.length) return;
  const item = Voice.queue.shift();
  Voice.playing = true;
  const done = () => { Voice.playing = false; pumpSpeech(); };

  if (!G.meta.tts || !G.sid) { speakFallback(item.text, done); return; }
  fetch("/api/tts?sid=" + G.sid, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: item.name, text: item.text }),
  })
    .then((r) => {
      if (!r.ok) throw new Error("tts " + r.status);
      return r.blob();
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.defaultPlaybackRate = SPEECH_RATE;
      audio.playbackRate = SPEECH_RATE;
      audio.onended = audio.onerror = () => { URL.revokeObjectURL(url); done(); };
      return audio.play().catch(() => { URL.revokeObjectURL(url); done(); });
    })
    .catch(() => speakFallback(item.text, done));   // offline / error → browser voice
}

/* plain browser speech synthesis — the no-API fallback */
function speakFallback(text, done) {
  if (!("speechSynthesis" in window)) { done(); return; }
  const u = new SpeechSynthesisUtterance(text);
  const want = voiceLang();
  u.lang = want;
  const voices = speechSynthesis.getVoices();
  const v = voices.find((x) => x.lang === want)
        || voices.find((x) => x.lang && x.lang.indexOf(want.slice(0, 2)) === 0);
  if (v) u.voice = v;
  u.rate = SPEECH_RATE;
  u.onend = u.onerror = done;
  speechSynthesis.speak(u);
}

function updateTtsButton() {
  const btn = $("btn-tts");
  btn.textContent = Voice.ttsOn ? "🔊" : "🔇";
  btn.classList.toggle("off", !Voice.ttsOn);
}

$("btn-tts").addEventListener("click", () => {
  Voice.ttsOn = !Voice.ttsOn;
  localStorage.setItem("holdem_tts", Voice.ttsOn ? "1" : "0");
  if (!Voice.ttsOn) {
    Voice.queue.length = 0;
    if (window.speechSynthesis) speechSynthesis.cancel();
  }
  updateTtsButton();
});

/* ------------------------- input: you talk ------------------------- */

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

/* "两百三十" -> 230. Chinese ASR usually emits digits already; this catches
 * the spelled-out amounts it sometimes produces instead. */
function zhNumber(s) {
  const D = { "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9 };
  const U = { "十": 10, "百": 100, "千": 1000 };
  let total = 0, section = 0, num = 0, any = false;
  for (const ch of s) {
    if (D[ch] !== undefined) { num = D[ch]; any = true; }
    else if (U[ch] !== undefined) {
      section += (num || 1) * U[ch];
      num = 0; any = true;
    } else if (ch === "万") {
      total = (total + section + num) * 10000;
      section = 0; num = 0; any = true;
    }
  }
  return any ? total + section + num : null;
}

function parseAmount(s) {
  if (!s) return null;
  const digits = String(s).match(/\d+/);
  if (digits) return parseInt(digits[0], 10);
  return zhNumber(String(s));
}

/* Map a transcript to a game command, or null for plain table talk. */
function voiceCommand(raw) {
  const s = raw.toLowerCase().replace(/[.,!?。，！？、]+/g, " ").replace(/\s+/g, " ").trim();
  if (G.mode === "action") {
    if (/(^| )fold(s|ing)?( |$)|弃牌|我弃|不跟/.test(s)) return "f";
    if (/(^| )check( |$)|过牌|看牌/.test(s)) return "c";
    if (/all ?in|shove|jam|全下|全押|梭哈/.test(s)) return "a";
    let m = s.match(/(?:raise(?: to)?|bet)\s+([\w]+)/)
         || s.match(/(?:加注到|加到|加注|下注)\s*([零一二两三四五六七八九十百千万\d]+)/);
    if (m) {
      const amt = parseAmount(m[1]);
      if (amt) return "r " + amt;
    }
    if (/(^| )call(s)?( |$)|跟注|我跟|跟了/.test(s)) return "c";
  } else if (G.mode === "between") {
    let m = s.match(/buy\s+([\w]+)/)
         || s.match(/买\s*([零一二两三四五六七八九十百千万\d]+)/);
    if (m) {
      const amt = parseAmount(m[1]);
      if (amt) return "buy " + amt;
    }
    if (/next hand|deal|下一手|下一把|发牌|继续/.test(s)) return "";
  }
  return null;
}

function handleVoiceResult(text) {
  text = text.trim();
  if (!text) return;
  feed(`🎤 <span class="dim">${t("heard")}:</span> ${esc(text)}`, "sys");
  const cmd = voiceCommand(text);
  if (cmd === null) {                       // not a move — table talk, any time
    if (G.mode === "text") { postInput(text); G.mode = null; }
    else sendChat(text);
    return;
  }
  if (cmd === "") {                         // "next hand"
    $("between").classList.add("disabled");
    G.mode = null;
    postInput("");
    return;
  }
  if (cmd.indexOf("buy ") === 0) { postInput(cmd); return; }
  act(cmd);                                 // f / c / a / r N — like a click
}

function startListening() {
  const rec = new SR();
  Voice.rec = rec;
  rec.lang = voiceLang();
  rec.interimResults = true;
  rec.maxAlternatives = 1;
  let finalText = "";
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
      else interim += e.results[i][0].transcript;
    }
    $("say-input").value = finalText || interim;   // live feedback while talking
  };
  rec.onend = () => {
    Voice.listening = false;
    Voice.rec = null;
    $("btn-mic").classList.remove("listening");
    $("say-input").value = "";
    if (finalText) handleVoiceResult(finalText);
  };
  rec.onerror = () => {};   // onend still fires and cleans up
  Voice.listening = true;
  $("btn-mic").classList.add("listening");
  rec.start();
}

function stopListening() {
  if (Voice.rec) Voice.rec.stop();   // onend delivers whatever was heard
}

if (SR) {
  $("btn-mic").addEventListener("click", () => {
    if (Voice.listening) stopListening();
    else startListening();
  });
} else {
  $("btn-mic").style.display = "none";   // no Web Speech API (e.g. Firefox)
}

/* some browsers load the voice list asynchronously — warm it up */
if ("speechSynthesis" in window) speechSynthesis.getVoices();
updateTtsButton();
