"""
ARISA - At-risk Interactive Student Advisor-trainer
Flask prototype: persona-driven at-risk student simulation for advisor practice.

Wilson Sun (520455553) - INFO4001/INFO4002
Supervisors: Prof. Judy Kay, Timothy Dutton
University of Sydney
"""

import os
import re
import json
import uuid
import datetime

import requests
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ARISA_MODEL", "claude-sonnet-4-6")
TEMPERATURE = float(os.environ.get("ARISA_TEMPERATURE", "1.0"))

DATA_DIR = os.environ.get("ARISA_DATA_DIR", os.path.join(os.path.dirname(__file__), "data", "sessions"))
os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Server-side session store.
#
# The Flask cookie session caps at ~4KB. A full 30-minute advising transcript
# exceeds that, and Flask drops the oversized cookie silently, which would lose
# the persona mid-session. The cookie therefore holds only a session id, and all
# state lives here.
#
# NOTE FOR DEPLOYMENT: this dict is per-process. It is fine for a single-worker
# local or single-instance deployment. If ARISA is deployed on AWS behind more
# than one worker or instance, replace this with Redis or another shared store,
# or pin gunicorn to one worker (--workers 1).
# ---------------------------------------------------------------------------
SESSIONS = {}

# Attributes shown to the advisor in the pre-session brief.
VISIBLE_ATTRIBUTES = ["wam_trend", "failed_units", "attendance", "academic_standing"]

# Attributes withheld in the brief and shown as labelled rows with values hidden.
# These, and only these, are what the elicitation check scores: the advisor
# cannot "elicit" something they were handed on the previous screen.
HIDDEN_ATTRIBUTES = [
    ("stressor", "Primary stressor"),
    ("living_situation", "Living situation"),
    ("help_seeking", "Help-seeking tendency"),
]


PERSONAS = {
    "amy": {
        "id": "A",
        "name": "Amy Chen",
        "age": 19,
        "gender": "Woman",
        "year": 2,
        "faculty": "Engineering",
        "degree": "B.Engineering (Software)",
        "living_situation": "rents a room in Parramatta, commutes to Camperdown campus",
        "stressor_label": "Casual employment",
        "stressor_detail": (
            "Works 28 hrs/week in hospitality, irregular late shifts, out of "
            "financial necessity. Will not volunteer her financial situation "
            "or employment hours unprompted - must be asked specifically."
        ),
        "tone": "sceptical and guarded, minimises difficulties when asked directly",
        "wam_trend": [52, 48, 45],
        "failed_units": "INFO1110, INFO1111, MATH1061 (all core)",
        "enrolment": 4,
        "attendance": 40,
        "academic_standing": "Show Cause - third or subsequent occasion not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "minimises difficulties when asked directly, opens up only under specific questioning",
    },
    "ben": {
        "id": "B",
        "name": "Ben Reed",
        "age": 21,
        "gender": "Man",
        "year": 3,
        "faculty": "Business School",
        "degree": "B.Commerce",
        "living_situation": "lives at home with family in North Shore Sydney",
        "stressor_label": "Passing away of a family member",
        "stressor_detail": (
            "Parent passed away six months ago. A previously strong student "
            "with a sharp recent decline. Does not resist disclosure but "
            "needs space before he will share what has happened - direct "
            "questioning will cause him to withdraw further."
        ),
        "tone": "quiet and withdrawn, needs space before disclosure",
        "wam_trend": [71, 70, 51],
        "failed_units": "two units failed this semester",
        "enrolment": 4,
        "attendance": 45,
        "academic_standing": "At-risk - first occasion not meeting progression requirements",
        "prior_sessions": 1,
        "help_seeking": "attended a prior session but did not follow through on referrals",
    },
    "chloe": {
        "id": "C",
        "name": "Chloe Shaw",
        "age": 20,
        "gender": "Woman",
        "year": 2,
        "faculty": "Science",
        "degree": "B.Science",
        "living_situation": "student accommodation on campus, limited peer connection",
        "stressor_label": "Motivational disengagement",
        "stressor_detail": (
            "No identified external stressor. Stopped attending mid-semester "
            "by choice. Degree is not what she expected and she has not "
            "formed an alternative direction. Offers nothing voluntarily."
        ),
        "tone": "flat and indifferent, present because required to be",
        "wam_trend": [53, 47, 44],
        "failed_units": "three units failed, did not attempt recent final exams",
        "enrolment": 4,
        "attendance": 20,
        "academic_standing": "Show Cause - third or subsequent occasion not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "offers nothing voluntarily, will acknowledge with brief answers if asked with genuine curiosity",
    },
    "dean": {
        "id": "D",
        "name": "Dean Patel",
        "age": 22,
        "gender": "Man",
        "year": 2,
        "faculty": "Engineering",
        "degree": "B.Engineering (Electrical)",
        "living_situation": "lives at home with family, caring responsibilities based there",
        "stressor_label": "Carer responsibility",
        "stressor_detail": (
            "Primary carer for a parent with a chronic health condition. "
            "Treats this as a private family matter with no bearing on the "
            "advising session - discloses only under appropriate questioning."
        ),
        "tone": "polite and composed, treats caring role as private",
        "wam_trend": [55, 50, 46],
        "failed_units": "three core engineering units failed due to missed classes and fatigue",
        "enrolment": 4,
        "attendance": 35,
        "academic_standing": "Show Cause - third or subsequent occasion not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "gives vague answers to personal questions, matter-of-fact rather than emotional if disclosed",
    },
    "ella": {
        "id": "E",
        "name": "Ella Lane",
        "age": 20,
        "gender": "Woman",
        "year": 2,
        "faculty": "Arts and Social Sciences",
        "degree": "B.Arts (Psychology)",
        "living_situation": "recently moved out of student accommodation, living alone in inner west Sydney",
        "stressor_label": "Family conflict",
        "stressor_detail": (
            "Parental separation and ongoing family conflict, isolation from "
            "moving off campus, increased assessment anxiety. Willing to "
            "talk and opens up on academic impact before personal cause - "
            "avoids the family situation unless directly asked."
        ),
        "tone": "articulate about academic symptoms, avoidant on personal cause",
        "wam_trend": [64, 63, 51],
        "failed_units": "one unit failed, assessment anxiety worsening",
        "enrolment": 4,
        "attendance": 55,
        "academic_standing": "At-risk - first occasion not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "articulate about academic symptoms, avoids discussing family situation unless directly asked",
    },
    "finn": {
        "id": "F",
        "name": "Finn Nguyen",
        "age": 20,
        "gender": "Man",
        "year": 2,
        "faculty": "Business School",
        "degree": "B.Commerce",
        "living_situation": "lives at home with family in south-west Sydney, crowded household affecting study environment",
        "stressor_label": "English language barrier",
        "stressor_detail": (
            "English is a second language. Attends regularly and works "
            "hard, but written assessment results do not reflect effort - "
            "quantitative units are passing. Open if support is framed as "
            "skill-building, will deflect with 'I just need to work harder' "
            "if the advisor implies the problem is effort."
        ),
        "tone": "polite and earnest, genuinely wants help",
        "wam_trend": [58, 55, 49],
        "failed_units": "two units with significant written assessment components",
        "enrolment": 4,
        "attendance": 90,
        "academic_standing": "At-risk - first occasion not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "open if support framed as skill-building, deflects if problem framed as low effort",
    },
    # Warm-up persona. Not part of the six-persona set: cooperative, no
    # disclosure resistance, used to familiarise the advisor with the interface
    # before harder personas. See thesis section on session sequencing.
    "jamie": {
        "id": "W",
        "name": "Jamie Lee",
        "age": 18,
        "gender": "Non-binary",
        "year": 1,
        "faculty": "Science",
        "degree": "B.Science",
        "living_situation": "lives with family, short commute to campus",
        "stressor_label": "Adjusting to university workload",
        "stressor_detail": (
            "No major external stressor. Struggling to adjust to the pace and "
            "independence of first-year study. Attends the session voluntarily "
            "and volunteers information readily when asked general questions."
        ),
        "tone": "open, cooperative, a little anxious but forthcoming",
        "wam_trend": [58, 56, 53],
        "failed_units": "one unit failed",
        "enrolment": 4,
        "attendance": 65,
        "academic_standing": "At-risk - first occasion not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "proactive, volunteers information readily and expands willingly when asked general questions",
        "warmup": True,
    },
}


def year_label(year):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(year, f"{year}th")


def build_system_prompt(persona):
    wam_str = " -> ".join(str(w) for w in persona["wam_trend"])
    warmup_note = ""
    if persona.get("warmup"):
        warmup_note = (
            "\n- You are cooperative and forthcoming. Answer general questions "
            "with useful detail rather than deflecting."
        )
    return f"""You are role-playing as {persona['name']}, a {year_label(persona['year'])} year {persona['degree']} student in the {persona['faculty']} at the University of Sydney, in a mandatory academic advising session.

IDENTITY (fixed - never change):
- Age: {persona['age']}
- Living situation: {persona['living_situation']}
- Primary stressor: {persona['stressor_label']} - {persona['stressor_detail']}
- Speaking tone: {persona['tone']}

INTERNAL PROFILE (only share if asked directly and specifically):
- WAM trend: {wam_str} (declining)
- Failed units: {persona['failed_units']}
- Current enrolment: {persona['enrolment']} units
- Attendance last semester: {persona['attendance']}%
- Academic standing: {persona['academic_standing']}
- Prior advising sessions: {persona['prior_sessions']}
- Help-seeking tendency: {persona['help_seeking']}

RULES:
- Remain in character at all times, never break character.
- Do not volunteer academic or personal details unless directly asked. Open with brief, deflective answers.
- If asked a general question ("how are you going?"), give a short, guarded reply. Only add detail if the advisor probes further.
- Keep responses to 2-4 sentences, informal language matching your assigned tone.
- Never mention WAM, failed units, or your stressor unless asked about it specifically.
- If asked about disability, mental health crisis, or harassment: briefly decline to discuss it, do not elaborate.
- Do not give advice or step outside the student role.{warmup_note}"""


def call_claude(system_prompt, messages, max_tokens=500, model=None, temperature=None):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=your_key_here"
        )
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model or MODEL,
            "max_tokens": max_tokens,
            "temperature": TEMPERATURE if temperature is None else temperature,
            "system": system_prompt,
            "messages": messages,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    return ""


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_state():
    sid = session.get("sid")
    if not sid:
        return None
    return SESSIONS.get(sid)


def new_state(persona_key):
    sid = str(uuid.uuid4())
    session["sid"] = sid
    SESSIONS[sid] = {
        "sid": sid,
        "persona_key": persona_key,
        "persona": PERSONAS[persona_key],
        "messages": [],
        "self_rating": None,
        "elicitation": None,
        "model": MODEL,
        "temperature": TEMPERATURE,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ended_at": None,
    }
    return SESSIONS[sid]


def persist(state):
    """Write the session record to disk. This is the user study's raw data."""
    path = os.path.join(DATA_DIR, f"{state['sid']}.json")
    record = dict(state)
    record["persona"] = {"key": state["persona_key"], "name": state["persona"]["name"]}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
    except OSError as e:
        app.logger.error("Could not persist session %s: %s", state["sid"], e)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/personas", methods=["GET"])
def api_personas():
    return jsonify([
        {
            "key": key,
            "id": p["id"],
            "name": p["name"],
            "faculty": p["faculty"],
            "differentiator": p["stressor_label"],
            "warmup": p.get("warmup", False),
            "initials": "".join(w[0] for w in p["name"].split()[:2]).upper(),
        }
        for key, p in PERSONAS.items()
    ])


@app.route("/api/generate", methods=["POST"])
def api_generate():
    key = request.json.get("persona_key") if request.is_json else None
    if key not in PERSONAS:
        return jsonify({"error": "Unknown persona. Pick one from the list."}), 400
    state = new_state(key)
    persona = state["persona"]
    return jsonify({
        "persona": persona,
        "system_prompt": build_system_prompt(persona),
        "hidden_labels": [label for _, label in HIDDEN_ATTRIBUTES],
        "year_label": year_label(persona["year"]),
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    state = get_state()
    if not state:
        return jsonify({"error": "This session has expired. Start a new one."}), 400

    user_text = (request.json.get("message") or "").strip()
    if not user_text:
        return jsonify({"error": "Type a question before sending."}), 400

    state["messages"].append({"role": "user", "content": user_text})
    try:
        reply = call_claude(build_system_prompt(state["persona"]), state["messages"])
    except requests.HTTPError as e:
        state["messages"].pop()
        return jsonify({"error": f"The model did not respond ({e.response.status_code}). Try again."}), 502
    except Exception as e:
        state["messages"].pop()
        return jsonify({"error": str(e)}), 500

    state["messages"].append({"role": "assistant", "content": reply})
    return jsonify({"reply": reply})


@app.route("/api/self-rating", methods=["POST"])
def api_self_rating():
    """
    Advisor self-rating, captured after the conversation and before any
    comparison data is shown. Ordering is deliberate: the rating must reflect
    the advisor's own sense of the session, uncontaminated by the elicitation
    table. See thesis section on OLM interface design.
    """
    state = get_state()
    if not state:
        return jsonify({"error": "This session has expired. Start a new one."}), 400
    try:
        rating = int(request.json.get("rating"))
    except (TypeError, ValueError):
        return jsonify({"error": "Choose a rating from 1 to 7."}), 400
    if not 1 <= rating <= 7:
        return jsonify({"error": "Choose a rating from 1 to 7."}), 400

    state["self_rating"] = rating
    state["rated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    persist(state)
    return jsonify({"ok": True})


@app.route("/api/debrief", methods=["POST"])
def api_debrief():
    state = get_state()
    if not state:
        return jsonify({"error": "This session has expired. Start a new one."}), 400

    persona = state["persona"]
    transcript = "\n".join(
        f"{'Advisor' if m['role'] == 'user' else persona['name']}: {m['content']}"
        for m in state["messages"]
    )

    # Only the withheld attributes are scored. The academic data layer was shown
    # to the advisor in the pre-session brief, so "eliciting" it is not a
    # meaningful measure of anything.
    attribute_block = "\n".join(
        f"- {label}: {persona['stressor_label'] + ' - ' + persona['stressor_detail'] if k == 'stressor' else persona[k]}"
        for k, label in HIDDEN_ATTRIBUTES
    )
    expected = json.dumps(
        [{"attribute": label, "elicited": False, "evidence": ""} for _, label in HIDDEN_ATTRIBUTES]
    )

    judge_prompt = f"""Here is a transcript of an academic advising practice session.

The student's true profile for the withheld attributes is:
{attribute_block}

Transcript:
{transcript}

For each withheld attribute, decide whether the advisor drew it out during the
session. Count it as elicited only if the student actually disclosed it in the
transcript, not if the advisor merely gestured at the topic. Quote the student
turn that shows it, or leave evidence empty.

Respond with ONLY a JSON array in exactly this form:
{expected}"""

    try:
        raw = call_claude(
            "You are an evaluation assistant. Reply with valid JSON only.",
            [{"role": "user", "content": judge_prompt}],
            max_tokens=700,
            temperature=0,
        )
        cleaned = re.sub(r"```json|```", "", raw).strip()
        elicitation = json.loads(cleaned)
    except json.JSONDecodeError as e:
        app.logger.error("Debrief judge returned unparseable JSON: %s", e)
        elicitation = []
    except Exception as e:
        app.logger.error("Debrief judge call failed: %s", e)
        elicitation = []

    state["elicitation"] = elicitation
    state["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    persist(state)

    return jsonify({
        "persona": persona,
        "elicitation": elicitation,
        "self_rating": state["self_rating"],
        "full_profile": [
            {"label": label,
             "value": (persona["stressor_label"] + " - " + persona["stressor_detail"])
             if k == "stressor" else persona[k]}
            for k, label in HIDDEN_ATTRIBUTES
        ],
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    sid = session.pop("sid", None)
    if sid:
        state = SESSIONS.pop(sid, None)
        # An abandoned session is still a result. Record it rather than
        # dropping it, but only if the advisor actually said something.
        if state and state["messages"]:
            state["abandoned"] = True
            state["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            persist(state)
    return jsonify({"ok": True})


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "model": MODEL, "sessions": len(SESSIONS)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)