# ARISA prototype

A minimal, working demo of the ARISA advising simulation: persona generation,
pre-session OLM brief, live chat with the simulated student, and a
post-session elicitation debrief.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here    # get one at console.anthropic.com
python app.py
```

Then open http://localhost:5000 in your browser.

## What this demonstrates

1. **Setup** — generates a randomised at-risk student persona from the
   identity/trouble-area logic in `app.py` (`generate_persona()`).
2. **Pre-session brief** — the two-layer OLM view: academic data visible,
   personal context rows shown but redacted, matching the thesis design.
3. **Advising session** — a live chat with the persona, powered by Claude.
   Click "Show system prompt" to see exactly what's fixed for the persona
   versus what it's instructed to reveal only when asked
   (`build_system_prompt()` in `app.py`).
4. **Debrief** — after ending the session, a second Claude call judges the
   transcript against the persona's true profile and shows which attributes
   the advisor successfully elicited.

## Files

- `app.py` — Flask backend: persona generation, prompt construction, and the
  three API routes (`/api/generate`, `/api/chat`, `/api/debrief`)
- `templates/index.html` — single-page frontend, vanilla JS, no build step

## Notes

- Only 8 of the trouble-area types are implemented in full; extend
  `TROUBLE_AREAS` in `app.py` to add the remaining ones from the original
  prompt spec.
- Elicitation is checked via a single LLM judge call at the end of the
  session, not live during the conversation.
- Session state (persona + transcript) is stored server-side via Flask
  session cookies — fine for a local demo, would need a proper session
  store for multi-user deployment.
