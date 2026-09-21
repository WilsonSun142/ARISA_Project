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
PROMPT_DIR = os.environ.get("ARISA_PROMPT_DIR", os.path.join(os.path.dirname(__file__), "prompts"))
def load_template(filename):
    path = os.path.join(PROMPT_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

SYSTEM_PROMPT_TEMPLATE = load_template("system_prompt.md")
VERIFIER_PROMPT_TEMPLATE = load_template("verifier_prompt.md")

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
VISIBLE_ATTRIBUTES = ["wam_trend", "failed_units", "academic_standing"]

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
        "differentiator": "Employment competing with study time; deflects under direct questioning",
        "living_situation": "rents a room in Parramatta, commutes to Camperdown campus",
        "stressor_label": "Casual employment",
        "stressor_detail": (
            "Works 28 hrs/week in hospitality, irregular late shifts, out of "
            "financial necessity. Will not volunteer her financial situation "
            "or employment hours unprompted - must be asked specifically."
        ),
        "tone": "sceptical and guarded, minimises difficulties when asked directly",
        "wam_trend": [52, 48, 45],
        "failed_units": (
            "INFO1110 (Introduction to Programming), failed three times; "
            "INFO1113 (Object-Oriented Programming), failed twice"
        ),
        "enrolment": 4,
        "academic_standing": "Show Cause - required to show good cause why re-enrolment should be permitted",
        "prior_sessions": 0,
        "help_seeking": "minimises difficulties when asked directly, opens up only under specific questioning",
        "design_intent": [
            "How many hours is she actually working, and when?",
            "Is employment financially necessary or partially optional?",
            "Does she know load reduction or timetable adjustment are options?",
            "Has she accessed any support services previously?",
            "What would make it possible for her to reduce hours or restructure commitments?",
        ],
    },
    "ben": {
        "id": "B",
        "name": "Ben Clarke",
        "age": 21,
        "gender": "Man",
        "year": 3,
        "faculty": "Business School",
        "degree": "B.Commerce",
        "differentiator": "Loss of a parent; previously strong student; needs space before disclosure",
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
        "failed_units": (
            "BUSS2000 (Leading and Influencing in Business), "
            "FINC2011 (Corporate Finance I)"
        ),
        "enrolment": 4,
        "academic_standing": "At-risk - identified as at risk of not meeting progression requirements",
        "prior_sessions": 1,
        "help_seeking": "attended a prior session but did not follow through on referrals",
        "design_intent": [
            "What has changed this semester compared to his previous strong performance?",
            "Has something happened personally that has affected his ability to study?",
            "Is he aware that the Student Counselling Service exists at USYD?",
            "Why did he not follow through on prior referrals, and what would make it easier this time?",
            "What support would help him reengage with his studies?",
        ],
    },
    "chloe": {
        "id": "C",
        "name": "Chloe Bennett",
        "age": 20,
        "gender": "Woman",
        "year": 2,
        "faculty": "Science",
        "degree": "B.Science",
        "differentiator": "Motivational disengagement without external stressor; requires values exploration not referral",
        "living_situation": "student accommodation on campus, limited peer connection",
        "stressor_label": "Motivational disengagement",
        "stressor_detail": (
            "No identified external stressor. Stopped attending mid-semester "
            "by choice. Degree is not what she expected and she has not "
            "formed an alternative direction. Offers nothing voluntarily."
        ),
        "tone": "flat and indifferent, present because required to be",
        "wam_trend": [53, 47, 44],
        "failed_units": (
            "CHEM1001 (Chemistry 1A), failed twice, final exam not attempted on the second occasion "
            "BIOL1006 (Life and Evolution)"
        ),
        "enrolment": 4,
        "academic_standing": "Academic Caution - identified as not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "offers nothing voluntarily, will acknowledge with brief answers if asked directly with genuine curiosity",
        "design_intent": [
            "Is there an external stressor driving the disengagement, or is this motivational?",
            "What was her expectation of the degree and how does it differ from reality?",
            "Does she feel connected to anyone or anything at university?",
            "Has she considered what she actually wants to do?",
            "What would need to change for her to feel like the degree is worth continuing?",
        ],


    },
    "dean": {
        "id": "D",
        "name": "Dean Patel",
        "age": 22,
        "gender": "Man",
        "year": 2,
        "faculty": "Engineering",
        "degree": "B.Engineering (Electrical)",
        "differentiator": "Carer responsibility treated as private; advisor must recognise what is not being said",
        "living_situation": "lives at home with family, caring responsibilities based there",
        "stressor_label": "Carer responsibility",
        "stressor_detail": (
            "Primary carer for a parent with a chronic health condition. "
            "Treats this as a private family matter with no bearing on the "
            "advising session - discloses only under appropriate questioning."
        ),
        "tone": "polite and composed, treats caring role as private",
        "wam_trend": [55, 50, 46],
        "failed_units": (
            "MATH1061 (Mathematics 1A), failed twice; "
            "INFO1110 (Introduction to Programming); "
            "ELEC1004 (Practical Intro to Electrical Engineering)"
        ),
        "enrolment": 4,
        "academic_standing": "Academic Caution - identified as not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "gives vague answers to personal questions, matter-of-fact rather than emotional if disclosed",
        "design_intent": [
            "What is making a typical week difficult to manage?",
            "Is there a caring or family responsibility that affects his availability?",
            "Is he aware that USYD carer support services exist?",
            "Would load reduction or flexible assessment arrangements help?",
            "What does he need in order to continue his degree without the current level of attrition?",
        ],

    },
    "ella": {
        "id": "E",
        "name": "Ella Anderson",
        "age": 20,
        "gender": "Woman",
        "year": 2,
        "faculty": "Arts and Social Sciences",
        "degree": "B.Arts (Psychology)",
        "differentiator": "Emotional distraction from family conflict; articulate about academic impact, avoidant on cause",
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
        "failed_units": "PSYC2015 (Brain and Behavioural Psychology)",
        "enrolment": 4,
        "academic_standing": "At-risk - identified as at risk of not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "articulate about academic symptoms, avoids discussing family situation unless directly asked",
        "design_intent": [
            "What has changed in her personal life that coincides with the academic decline?",
            "Is the family situation ongoing and actively affecting her concentration?",
            "Has the move off campus increased her isolation?",
            "Is she aware that counselling exists and what has stopped her from making contact?",
            "What would help her feel less alone while managing the family situation?",
        ],

    },
    "finn": {
        "id": "F",
        "name": "Finn Nguyen",
        "age": 20,
        "gender": "Non-binary",
        "pronouns": "they/them",
        "year": 2,
        "faculty": "Business School",
        "degree": "B.Commerce",
        "differentiator": "Frequently misgendered and socially isolated; tests whether the advisor's own language creates safety before questioning begins",
        "living_situation": "lives at home with family in south-west Sydney",
        "stressor_label": "Social isolation and repeated misgendering",
        "stressor_detail": (
            "Frequently and unintentionally misgendered by classmates and "
            "tutors. Finds university social spaces exhausting and has not "
            "found a peer group who understands their situation. Correcting "
            "people repeatedly has come to feel like more effort than it is "
            "worth, so Finn has largely stopped trying and withdrawn "
            "instead. Will not raise the isolation unless the advisor's own "
            "language signals it is safe to - otherwise attributes the "
            "decline to vague 'motivation' issues."
        ),
        "tone": "polite but guarded, watches how the advisor speaks before deciding how much to say",
        "wam_trend": [58, 55, 49],
        "failed_units": (
            "BUSS1030 (Accounting for Decision Making), "
            "BUSS2000 (Leading and Influencing in Business)"
        ),
        "enrolment": 4,
        "academic_standing": "At-risk - identified as at risk of not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "will not raise the isolation unless the advisor's own language signals it is safe to, otherwise attributes the decline to vague 'motivation' issues",
        "design_intent": [
            "What does a typical week look like socially, not just academically?",
            "Has Finn found any groups, clubs, or peers at university they feel comfortable with?",
            "Is something making it harder to connect with people here than expected?",
            "Is Finn aware that university LGBTQ+ and diversity support services exist?",
            "What would make university feel less exhausting to navigate day to day?",
        ],

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
        "differentiator": "Familiarisation with the interface and conversation flow",
        "living_situation": "lives with family, short commute to campus",
        "stressor_label": "Adjusting to university workload",
        "stressor_detail": (
            "No major external stressor. Struggling to adjust to the pace and "
            "independence of first-year study. Attends the session voluntarily "
            "and volunteers information readily when asked general questions."
        ),
        "tone": "open, cooperative, a little anxious but forthcoming",
        "wam_trend": [],
        "failed_units": (
            "CHEM1011 (Fundamentals of Chemistry 1A), MATH1061 (Mathematics 1A)"
        ),
        "enrolment": 4,
         "academic_standing": "At-risk - identified as at risk of not meeting progression requirements",
        "prior_sessions": 0,
        "help_seeking": "proactive, volunteers information readily and expands willingly when asked general questions",
        "warmup": True,
    },
}

# Fields safe to send before a session starts: the academic record layer
# only. Excludes differentiator (admin-only design documentation) and the
# three HIDDEN_ATTRIBUTES fields, which must not reach the client until
# debrief - sending them at brief time would let an advisor read the
# answer from the network tab, defeating the discovery design the
# benchmark and OLM are both built around.
BRIEF_PUBLIC_FIELDS = {
    "id", "name", "age", "gender", "pronouns", "year", "faculty", "degree",
    "tone", "wam_trend", "failed_units", "enrolment", "academic_standing",
    "prior_sessions", "warmup",
}


PERSONA_PUBLIC_FIELDS = {
    "id", "name", "age", "gender", "pronouns", "year", "faculty", "degree",
    "living_situation", "stressor_label", "stressor_detail", "tone",
    "wam_trend", "failed_units", "enrolment", "academic_standing",
    "prior_sessions", "help_seeking", "warmup",
}
def brief_persona(persona):
    return {k: v for k, v in persona.items() if k in BRIEF_PUBLIC_FIELDS}

def public_persona(persona):
    return {k: v for k, v in persona.items() if k in PERSONA_PUBLIC_FIELDS}

def year_label(year):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(year, f"{year}th")


def build_system_prompt(persona):
    if persona["wam_trend"]:
        wam_str = " -> ".join(str(w) for w in persona["wam_trend"]) + " (declining)"
    else:
        wam_str = "no history yet; this is your first semester of first year"
    warmup_note = ""
    if persona.get("warmup"):
        warmup_note = (
            "\n- You are cooperative and forthcoming. Answer general questions "
            "with useful detail rather than deflecting."
        )
    pronoun_line = f"\n- Pronouns: {persona['pronouns']}" if persona.get("pronouns") else ""
    return SYSTEM_PROMPT_TEMPLATE.format(
        name=persona["name"],
        year_label=year_label(persona["year"]),
        degree=persona["degree"],
        faculty=persona["faculty"],
        age=persona["age"],
        gender=persona["gender"],
        pronoun_line=pronoun_line,
        tone=persona["tone"],
        wam_str=wam_str,
        failed_units=persona["failed_units"],
        enrolment=persona["enrolment"],
        academic_standing=persona["academic_standing"],
        prior_sessions=persona["prior_sessions"],
        living_situation=persona["living_situation"],
        stressor_label=persona["stressor_label"],
        stressor_detail=persona["stressor_detail"],
        help_seeking=persona["help_seeking"],
        warmup_note=warmup_note,
    )

VERIFY_MAX_ATTEMPTS = 2

def build_verifier_prompt(persona):
    hidden_block = "\n".join(
        f"- {label}: {persona['stressor_label'] + ' - ' + persona['stressor_detail'] if k == 'stressor' else persona[k]}"
        for k, label in HIDDEN_ATTRIBUTES
    )
    return VERIFIER_PROMPT_TEMPLATE.format(
        name=persona["name"],
        hidden_block=hidden_block,
    )

def call_claude(system_prompt, messages, max_tokens=500, model=None, temperature=None):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=your_key_here"
        )
    payload = {
        "model": model or MODEL,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE if temperature is None else temperature,
        "system": system_prompt,
        "messages": messages,
    }
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json; charset=utf-8",
        },
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    return ""


def generate_checked_reply(persona, messages):
    """Generator-verifier loop mirroring DuetSim (Luo et al., 2024) and
    Ji et al.'s (2025) self-questioning, adapted to check PERSONAL CONTEXT
    disclosure rather than trait consistency. See thesis Section 3.3."""
    system_prompt = build_system_prompt(persona)
    verifier_prompt = build_verifier_prompt(persona)
    advisor_message = messages[-1]["content"]
    working_messages = list(messages)
    feedback = None
    reply = None

    for attempt in range(VERIFY_MAX_ATTEMPTS + 1):
        if feedback:
            working_messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": (
                    f"[SYSTEM NOTE, not visible to the advisor] Your last reply "
                    f"disclosed something it should not have: {feedback} "
                    f"Rewrite your reply to the advisor's last message without "
                    f"this disclosure, staying in character and tone."
                )},
            ]

        reply = call_claude(system_prompt, working_messages)

        raw_verdict = call_claude(
            verifier_prompt,
            [{"role": "user", "content": (
                f"Advisor's message: {advisor_message}\n\n"
                f"Candidate reply: {reply}"
            )}],
            max_tokens=200,
            temperature=0,
        ).strip()

        verdict_line = next(
            (line for line in raw_verdict.splitlines() if line.strip().upper().startswith("VERDICT:")),
            "",
        )
        verdict_content = verdict_line.split(":", 1)[1].strip() if ":" in verdict_line else verdict_line

        if verdict_content.upper().startswith("OK") or attempt == VERIFY_MAX_ATTEMPTS:
            return reply, attempt

        feedback = verdict_content.split(":", 1)[1].strip() if ":" in verdict_content else verdict_content

    return reply, VERIFY_MAX_ATTEMPTS


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
        "persona": brief_persona(persona),
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
        reply, verify_attempts = generate_checked_reply(state["persona"], state["messages"])
    except requests.HTTPError as e:
        state["messages"].pop()
        return jsonify({"error": f"The model did not respond ({e.response.status_code}). Try again."}), 502
    except Exception as e:
        state["messages"].pop()
        return jsonify({"error": str(e)}), 500

    state["messages"].append({"role": "assistant", "content": reply})
    state.setdefault("verify_log", []).append(verify_attempts)
    persist(state)
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

# ---------------------------------------------------------------------------
# Debrief scoring: 20-point rubric across five categories, each judged
# against direct evidence quoted from the transcript. Categories map onto
# the three advisor learning pillars (Section 1.4) and the per-persona
# design-intent questions (Chapter 4): disclosure specificity tests
# self-reflexive elicitation skill; question technique and collaborative
# conduct test respectful/collaborative practice; guidance quality and
# follow-up commitment test whether the session produced a real support
# plan, per Crookston's (1994) and Saiyad & Mahajan's (2023) framing of
# advising as collaborative plan development, not just information capture.
#
# The judge is run JUDGE_RUNS times at nonzero temperature and scores are
# averaged (self-consistency, per Wang et al., 2022, already cited in
# Section 4.2 via Kim et al., 2025), to reduce single-run judge noise -
# an explicit response to the "benchmark scoring is qualitative" limitation
# in Section 7.1.
# ---------------------------------------------------------------------------

JUDGE_RUNS = 3
JUDGE_TEMPERATURE = 0.5

DEBRIEF_SCORE_SCHEMA = {
    "disclosure": [
        {"attribute": None, "score": 0, "evidence": "", "reasoning": ""}
        for _ in range(3)
    ],
    "question_technique": {
        "open_vs_leading": {"score": 0, "evidence": "", "reasoning": ""},
        "design_intent_coverage": {"score": 0, "evidence": "", "reasoning": ""},
        "pacing": {"score": 0, "evidence": "", "reasoning": ""},
    },
    "collaborative_conduct": {
        "options_not_directives": {"score": 0, "evidence": "", "reasoning": ""},
        "escalation_boundaries": {"score": 0, "evidence": "", "reasoning": ""},
    },
    "guidance_quality": {"score": 0, "evidence": "", "reasoning": ""},
    "follow_up_commitment": {"score": 0, "evidence": "", "reasoning": ""},
}


def build_debrief_judge_prompt(persona, transcript):
    attribute_block = "\n".join(
        f"- {label}: {persona['stressor_label'] + ' - ' + persona['stressor_detail'] if k == 'stressor' else persona[k]}"
        for k, label in HIDDEN_ATTRIBUTES
    )
    academic_block = (
        f"- WAM trend: {' -> '.join(str(w) for w in persona['wam_trend']) if persona['wam_trend'] else 'no history yet'}\n"
        f"- Failed units: {persona['failed_units']}\n"
        f"- Academic standing: {persona['academic_standing']}"
    )
    design_intent_block = "\n".join(f"- {q}" for q in persona.get("design_intent", []))

    expected = json.dumps({
        "disclosure": [
            {"attribute": label, "score": 0, "evidence": "", "reasoning": ""}
            for _, label in HIDDEN_ATTRIBUTES
        ],
        "question_technique": {
            "open_vs_leading": {"score": 0, "evidence": "", "reasoning": ""},
            "design_intent_coverage": {"score": 0, "evidence": "", "reasoning": ""},
            "pacing": {"score": 0, "evidence": "", "reasoning": ""},
        },
        "collaborative_conduct": {
            "options_not_directives": {"score": 0, "evidence": "", "reasoning": ""},
            "escalation_boundaries": {"score": 0, "evidence": "", "reasoning": ""},
        },
        "guidance_quality": {"score": 0, "evidence": "", "reasoning": ""},
        "follow_up_commitment": {"score": 0, "evidence": "", "reasoning": ""},
    })

    return f"""Here is a transcript of an academic advising practice session with {persona['name']}.

The student's true profile for the withheld personal-context attributes is:
{attribute_block}

The student's academic record, already known to the advisor before the session, is:
{academic_block}

The attributes a skilled advisor would be expected to explore with this specific student are:
{design_intent_block}

Transcript:
{transcript}

Score the advisor's performance across five categories. For every score, quote the specific transcript turn(s) that justify it and briefly explain why that score was given rather than one above or below it.

1. DISCLOSURE (score each of the three withheld attributes independently, 0-3):
0 = Not elicited at all
1 = Volunteered with minimal prompting, or elicited only via a closed/leading question
2 = Directly asked and answered, no follow-up for specifics
3 = Advisor followed up to draw out concrete, specific detail (exact hours, named arrangement, a specific barrier), not just a surface acknowledgment

2. QUESTION TECHNIQUE (three sub-scores):
- open_vs_leading (0-2): 0 = mostly leading/closed questions; 1 = a mix; 2 = predominantly open questions that let the student state things in their own words
- design_intent_coverage (0-2): how many of the attributes a skilled advisor would explore (listed above) did the advisor actually raise, in substance if not the exact wording? 0 = none/one; 1 = some; 2 = most or all
- pacing (0-2): 0 = pressed on sensitive topics in a way that caused withdrawal or discomfort; 1 = adequate but rushed; 2 = paced appropriately for this student's disclosure pattern, including backing off if the student showed reluctance

3. COLLABORATIVE CONDUCT (two sub-scores):
- options_not_directives (0-1): did the advisor present options for the student to choose from, rather than prescribing a single directive solution?
- escalation_boundaries (0-1): if any sensitive out-of-scope topic arose (disability, mental health crisis, harassment), did the advisor respect the student's decline to discuss it without pushing further? Score 1 by default if no such topic arose.

4. GUIDANCE QUALITY (0-2, once for the whole session):
0 = No support options or guidance discussed
1 = Generic sympathy or encouragement, no concrete option
2 = A specific, relevant option offered (named service, load reduction, extension, referral) plausibly matched to what was disclosed or to the known academic record

5. FOLLOW-UP COMMITMENT (0-1, once for the whole session):
0 = No agreement on any next step, or the student did not commit to a suggested action
1 = The student explicitly agreed to a specific, named next step

Respond with ONLY a JSON object in exactly this form:
{expected}"""


def _score_of(item):
    try:
        return int(item.get("score", 0))
    except (TypeError, ValueError):
        return 0


def _total_score(judged):
    total = sum(_score_of(d) for d in judged.get("disclosure", []))
    qt = judged.get("question_technique", {})
    total += sum(_score_of(qt.get(k, {})) for k in ("open_vs_leading", "design_intent_coverage", "pacing"))
    cc = judged.get("collaborative_conduct", {})
    total += sum(_score_of(cc.get(k, {})) for k in ("options_not_directives", "escalation_boundaries"))
    total += _score_of(judged.get("guidance_quality", {}))
    total += _score_of(judged.get("follow_up_commitment", {}))
    return total


def run_debrief_judge(persona, transcript):
    """Run the debrief judge JUDGE_RUNS times at nonzero temperature and
    average numeric scores across runs (self-consistency). Evidence and
    reasoning text are kept from whichever run's total score is closest
    to the mean, as a representative sample rather than an average of text.
    Returns (aggregated_result, raw_runs) - raw_runs is kept for scrutability
    and appendix inclusion."""
    prompt = build_debrief_judge_prompt(persona, transcript)
    raw_runs = []

    for _ in range(JUDGE_RUNS):
        try:
            raw = call_claude(
                "You are an evaluation assistant. Reply with valid JSON only.",
                [{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=JUDGE_TEMPERATURE,
            )
            cleaned = re.sub(r"```json|```", "", raw).strip()
            judged = json.loads(cleaned)
            raw_runs.append(judged)
        except (json.JSONDecodeError, Exception) as e:
            app.logger.error("Debrief judge run failed: %s", e)

    if not raw_runs:
        return None, []

    totals = [_total_score(j) for j in raw_runs]
    mean_total = sum(totals) / len(totals)
    representative = raw_runs[min(range(len(raw_runs)), key=lambda i: abs(totals[i] - mean_total))]

    def avg_score(get_fn):
        vals = [get_fn(j) for j in raw_runs]
        return round(sum(vals) / len(vals), 1)
    rep_disclosure = representative.get("disclosure", [])

    def rep_field(i, field, default=""):
        return rep_disclosure[i].get(field, default) if i < len(rep_disclosure) else default

    aggregated = {
        "disclosure": [
            {
                "attribute": rep_field(i, "attribute", label),
                "score": avg_score(lambda j, i=i: _score_of(j["disclosure"][i]) if i < len(j.get("disclosure", [])) else 0),
                "evidence": rep_field(i, "evidence"),
                "reasoning": rep_field(i, "reasoning"),
            }
            for i, (_, label) in enumerate(HIDDEN_ATTRIBUTES)
        ],
        "question_technique": {
            k: {
                "score": avg_score(lambda j, k=k: _score_of(j.get("question_technique", {}).get(k, {}))),
                "evidence": representative.get("question_technique", {}).get(k, {}).get("evidence", ""),
                "reasoning": representative.get("question_technique", {}).get(k, {}).get("reasoning", ""),
            }
            for k in ("open_vs_leading", "design_intent_coverage", "pacing")
        },
        "collaborative_conduct": {
            k: {
                "score": avg_score(lambda j, k=k: _score_of(j.get("collaborative_conduct", {}).get(k, {}))),
                "evidence": representative.get("collaborative_conduct", {}).get(k, {}).get("evidence", ""),
                "reasoning": representative.get("collaborative_conduct", {}).get(k, {}).get("reasoning", ""),
            }
            for k in ("options_not_directives", "escalation_boundaries")
        },
        "guidance_quality": {
            "score": avg_score(lambda j: _score_of(j.get("guidance_quality", {}))),
            "evidence": representative.get("guidance_quality", {}).get("evidence", ""),
            "reasoning": representative.get("guidance_quality", {}).get("reasoning", ""),
        },
        "follow_up_commitment": {
            "score": avg_score(lambda j: _score_of(j.get("follow_up_commitment", {}))),
            "evidence": representative.get("follow_up_commitment", {}).get("evidence", ""),
            "reasoning": representative.get("follow_up_commitment", {}).get("reasoning", ""),
        },
        "total_score": round(mean_total, 1),
        "max_score": 20,
        "run_totals": totals,
    }
    return aggregated, raw_runs


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

    try:
        aggregated, raw_runs = run_debrief_judge(persona, transcript)
    except Exception as e:
        app.logger.error("Debrief scoring failed entirely: %s", e)
        aggregated, raw_runs = None, []

    state["debrief_score"] = aggregated
    state["debrief_judge_runs"] = raw_runs
    state["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    persist(state)

    return jsonify({
        "persona": public_persona(persona),
        "debrief_score": aggregated,
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