# ARISA prototype

At-Risk Interactive Student Advisor-trainer. An academic advisor practises a progression advising session with a simulated at-risk student driven by a large language model (LLM). After the session, the advisor rates their own performance, then reviews a debrief that opens their learner model beside the student's full persona record.

Developed for the Honours thesis *An LLM-Based Chatbot Training System for Academic Advisor Practice with At-Risk Students* (Wilson Sun, University of Sydney, 2026). Supervisors: Professor Judy Kay and Timothy Dutton.

## Access

ARISA is deployed on AWS EC2 at **http://3.106.75.11**. Open it in a browser. No installation is needed. The address may change if the server is restarted.

## Running locally (development)

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
python app.py
```

Then open http://localhost:5000.

Optional environment variables:

* `FLASK_SECRET`: secret key for session cookies. Set this to a long random value in any deployment.
* `ARISA_MODEL`: model name (default `claude-sonnet-4-6`).
* `ARISA_TEMPERATURE`: temperature for the simulated student (default `1.0`).

## Flow

1. **Setup:** choose a persona. Jamie Lee is a cooperative warm-up persona for learning the interface. The six at-risk personas (Amy, Ben, Chloe, Dean, Ella, Frankie) were reviewed by practising advising staff.
2. **Brief:** the academic record is shown (WAM trend, failed units, enrolment, standing, prior advising sessions). Three personal-context attributes (primary stressor, living situation, help-seeking tendency) are listed with their values withheld.
3. **Session:** live chat with the persona. Each reply is drafted by the student model, then checked by a separate verifier before it is shown.
4. **Self-rating:** a 7-point self-rating, captured before any score is shown.
5. **Debrief:** an LLM judge scores the transcript against a 20-point rubric derived from the learner model ontology. The scores are shown beside the full persona record, including what the advisor did not draw out.

## How it works

* **Persona records:** all seven personas are held in one Python dictionary (`PERSONAS` in `app.py`). The system prompt and the debrief are both generated from the same record, so they cannot drift apart.
* **System prompt:** built by `build_system_prompt()` from `prompts/system_prompt.md`, in four blocks: IDENTITY, ACADEMIC RECORD (what the advisor already has), PERSONAL CONTEXT (what the advisor must draw out) and RULES. Each persona has its own disclosure condition, the kind of question that leads that student to open up.
* **Verifier:** a separate model call at temperature 0, using `prompts/verifier_prompt.md`, checks each draft against the conversation so far. It fails replies that disclose withheld context too early, break character, refer to the student in the third person, or describe the rules. A failed draft is rewritten, up to two rewrites per reply.
* **Debrief judge:** runs three times at temperature 0.5 and returns integer scores only. Each criterion is averaged across the runs and rounded, then mapped to a fixed comment.
* **Model:** the student, verifier and judge all use Claude Sonnet 4.6, chosen from a four-model benchmark.

## Files

* `app.py`: Flask backend with the persona definitions (`PERSONAS`), prompt construction, verifier, debrief judge and API routes
* `prompts/system_prompt.md`: system prompt template for the simulated student
* `prompts/verifier_prompt.md`: verifier prompt template
* `templates/index.html`: single-page frontend
* `benchmark.py`: repeat-run consistency harness (see its docstring)

Session logs are written to `data/sessions/` at runtime. This folder is not included in the repository.

## Notes

* Personas are fixed, not randomly generated. An earlier version on Cogniti generated a random identity each session.
* The hidden context is concealed during the session and revealed in the debrief. Withheld fields are not sent to the browser until the debrief.
* Session state is stored server-side, keyed by a session-id cookie, because a full transcript exceeds Flask's default 4KB cookie-session limit.

## Deployment

Deployed on AWS EC2 at http://3.106.75.11. Runs via systemd (`arisa.service`) with gunicorn pinned to one worker, since session state is held in-process. Environment variables (API key, Flask secret) are read from `/etc/arisa.env`. nginx proxies port 80 to gunicorn on 127.0.0.1:8000.