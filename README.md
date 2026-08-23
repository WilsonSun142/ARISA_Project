# ARISA prototype

At-risk Interactive Student Advisor-trainer. An advisor practises an
advising session with an LLM-driven simulated at-risk student, then
reviews what they drew out against the underlying learner model.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
python app.py
```

Open http://localhost:5000.

## Flow

1. **Setup** — choose a persona. Jamie Lee is a warm-up persona for
   familiarisation; the six others (Amy, Ben, Chloe, Dean, Ella, Finn) are
   the validated set.
2. **Brief** — academic data is shown; three personal-context attributes
   (stressor, living situation, help-seeking tendency) are listed but
   withheld.
3. **Session** — live chat with the persona. "Show system prompt" reveals
   what's fixed versus what the persona is instructed to disclose only
   when asked (`build_system_prompt()` in `app.py`).
4. **Self-rating** — a 7-point rating captured before any comparison data
   is shown.
5. **Debrief** — an LLM judge checks the transcript against the three
   withheld attributes and reports what was drawn out.

## Files

- `app.py` — Flask backend: fixed persona definitions (`PERSONAS`),
  prompt construction, and API routes
- `templates/index.html` — single-page frontend
- `benchmark.py` — repeat-run consistency harness (see its own docstring)

## Notes

- Personas are fixed, not randomly generated; see `PERSONAS` in `app.py`
  for the seven identities and their profiles.
- Session state is stored server-side, keyed by a session-id cookie —
  chosen because a full transcript exceeds Flask's default 4KB
  cookie-session limit.
- Elicitation is checked via a single LLM judge call after the session,
  not live during the conversation.
- Deployed on AWS EC2 behind nginx; see deployment notes below.

## Deployment

Runs via systemd (`arisa.service`) with gunicorn pinned to one worker,
since session state is held in-process. Environment variables (API key,
Flask secret) are read from `/etc/arisa.env`. nginx proxies port 80 to
gunicorn on 127.0.0.1:8000.
