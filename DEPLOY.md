# Put Hold'em online — a link anyone can play

The whole game lives in one Python server (`webapp.py`): it serves the web
front-end *and* runs the shared poker engine, calling OpenAI for the AI
opponents. Deploy that one server and its URL is the link you share —
`https://<your-app>.onrender.com`.

> ⚠️ **Cost & safety.** With your key on the server, **every visitor's game
> spends your OpenAI credits**, and several people can play at once. Set a
> spending limit on your OpenAI account, and consider the **access code**
> option below before sharing the link widely.

## Deploy on Render (free)

1. Push this repo to GitHub.
2. Create a free account at <https://render.com> and connect your GitHub.
3. **New +  →  Blueprint**, pick this repo. Render reads `render.yaml` and
   proposes a free web service — click **Apply**.
4. Open the new service → **Environment** → **Add Environment Variable**:
   - `OPENAI_API_KEY` = your `sk-...` key. *(Never commit it; `render.yaml`
     intentionally leaves it blank.)*
   - optional `OPENAI_MODEL` (defaults to `gpt-5.2`, auto-falls back).
5. Wait for the deploy to go green, then open the service URL. That's the game;
   `…/healthz` should show `{"ok": true, ...}`.

> Render's free tier **sleeps after ~15 min idle**; the first visit after a nap
> takes ~30–60 s to load while the server wakes. Paid tiers stay awake.

*Prefer Hugging Face Spaces / Fly.io / Cloud Run instead? The included
`Dockerfile` runs there unchanged — create a Docker app from this repo and set
`OPENAI_API_KEY` as a secret. (HF Spaces: pick the **Docker** SDK; it serves on
port 7860, which the image already uses.)*

## Options worth setting before you share it widely

- **Require an access code** (protects your credits): set env `ACCESS_CODE` =
  some phrase. The site then asks each player for it once; tell it only to
  people you want playing. Leave it unset for a fully open link.
- **Cap concurrent tables**: env `MAX_GAMES` (default `12`). The oldest table
  is retired when the cap is hit.
- **Free games**: on the setup screen, players can tick **Offline (built-in
  bots, no API)** — that game uses the rule-based bots and spends nothing.
