# Put Hold'em online — a link anyone can play

The web version is a **Python server** (`webapp.py`): it runs the shared poker
engine and calls OpenAI for the AI opponents. GitHub Pages can only serve
*static* files, so it can't run that server or hold your API key. The setup is
therefore two halves that work together:

```
  https://<you>.github.io/Texas_Holdem_Agents/     <-- the link you share
        (GitHub Pages: static HTML/CSS/JS)
                     |  browser calls /api/... over HTTPS
                     v
  https://<your-app>.onrender.com                  <-- the real game
        (webapp.py + the shared engine + your OPENAI_API_KEY as a secret)
```

You do this once. After that, sharing the `github.io` link is all it takes.

> ⚠️ **Cost & safety.** With your key on the backend, **every visitor's game
> spends your OpenAI credits**, and several people can play at once. Set a
> spending limit on your OpenAI account, and consider the **access code** or
> **offline default** options at the bottom before sharing the link widely.

---

## Part A — the backend (Render, free)

1. Push this repo to GitHub (see the last section if you haven't).
2. Create a free account at <https://render.com> and connect your GitHub.
3. **New +  →  Blueprint**, pick this repo. Render reads `render.yaml` and
   proposes a free web service — click **Apply**.
4. Open the new service → **Environment** → **Add Environment Variable**:
   - `OPENAI_API_KEY` = your `sk-...` key. *(Never commit it; `render.yaml`
     intentionally leaves it blank.)*
   - optional `OPENAI_MODEL` (defaults to `gpt-5.2`, auto-falls back).
5. Wait for the deploy to go green, then note the URL, e.g.
   `https://texas-holdem-agents.onrender.com`. Open `…/healthz` — you should
   see `{"ok": true, ...}`.

> Render's free tier **sleeps after ~15 min idle**; the first game after a nap
> takes ~30–60 s to wake (the front-end shows a "waking up" note and retries).

*Prefer Hugging Face Spaces / Fly.io / Cloud Run instead? The included
`Dockerfile` runs there unchanged — create a Docker app from this repo and set
`OPENAI_API_KEY` as a secret. (HF Spaces: pick the **Docker** SDK; it serves on
port 7860, which the image already uses.)*

## Part B — the GitHub Pages front-end

1. Edit **`static/config.js`** and set `HOSTED_BACKEND` to your backend URL from
   Part A:
   ```js
   var HOSTED_BACKEND = "https://texas-holdem-agents.onrender.com";
   ```
2. Commit + push to `main`.
3. In the repo: **Settings → Pages → Build and deployment → Source:
   "GitHub Actions"**. (One time. The included `.github/workflows/pages.yml`
   publishes `static/` on every push.)
4. Watch the **Actions** tab; when the "Deploy web client" run finishes it
   prints your site URL:
   `https://<you>.github.io/Texas_Holdem_Agents/`.

**That link is the game.** Open it, click *Deal me in*, and you're playing the
LLM opponents through your backend. Share it with anyone.

---

## Options worth setting before you share it widely

- **Require an access code** (protects your credits): on the backend set env
  `ACCESS_CODE` = some phrase. The site then asks each player for it once; tell
  it only to people you want playing. Leave it unset for a fully open link.
- **Cap concurrent tables**: env `MAX_GAMES` (default `12`). The oldest table
  is retired when the cap is hit.
- **Free, zero-cost link**: on the setup screen, players can tick **Offline
  (built-in bots, no API)** — that game uses the rule-based bots and spends
  nothing. (A fully in-browser offline mode that needs no backend at all is
  planned — see the README roadmap.)
- **Lock the backend to your site**: set env `ALLOW_ORIGIN` =
  `https://<you>.github.io` so only your Pages site may call the API.

---

## If you need to push this repo first

```bash
git add -A
git commit -m "Add online deployment (GitHub Pages + hosted backend)"
git push origin main
```
