/* ===================== web client configuration =====================
 * Tells app.js WHERE the Python game engine (webapp.py) is reachable.
 *
 * Two situations, handled automatically:
 *   1. webapp.py serves this page itself  (local `python webapp.py`, or the
 *      hosted backend opened directly)      -> same origin, backend = "".
 *   2. GitHub Pages serves this page        (https://<you>.github.io/...)
 *      GitHub Pages is static and CANNOT run Python, so the browser must call
 *      your hosted backend instead. Paste that backend's https URL below.
 *
 * ── AFTER YOU DEPLOY THE BACKEND (see DEPLOY.md) ──
 *   set HOSTED_BACKEND to the URL your host gave you, e.g.
 *     "https://texas-holdem-agents.onrender.com"
 *   commit + push; the GitHub Pages site will then talk to it.
 * ==================================================================== */
(function () {
  // <-- EDIT THIS after deploying the backend (no trailing slash needed).
  var HOSTED_BACKEND = "https://REPLACE-ME.onrender.com";

  var onPages = /(^|\.)github\.io$/i.test(location.hostname);
  window.HOLDEM_BACKEND = onPages ? HOSTED_BACKEND.replace(/\/+$/, "") : "";
})();
