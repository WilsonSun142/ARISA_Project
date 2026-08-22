"""
ARISA benchmark harness with repeat runs.

Answers the question raised in supervision: how consistent is the simulation
when the same case is run more than once? None of the simulation systems
reviewed in the thesis report this, so a single reported interaction tells you
nothing about how reliably the behaviour reproduces.

For each (model, persona) pair the harness replays the benchmark prompt set
REPEATS times as independent sessions, scores every reply on the two risk
dimensions, and reports both the modal rating and how often the runs disagree.

Usage:
    export ANTHROPIC_API_KEY=...
    python benchmark.py --personas amy --repeats 5
    python benchmark.py --models claude-sonnet-4-6 --repeats 10 --out runs/

Output:
    <out>/raw.jsonl      one record per prompt per run
    <out>/summary.json   per model/persona consistency statistics
"""

import os
import re
import csv
import json
import time
import argparse
import datetime
from collections import Counter, defaultdict

from app import PERSONAS, build_system_prompt, call_claude

# ---------------------------------------------------------------------------
# Benchmark prompts.
#
# REPLACE THESE with the 15 prompts actually used in the Semester 1 benchmark.
# The layer structure below matches the thesis (Opening Q1-2, Explore Q3-4,
# Probe Q5-9, Plan Q10-13, Close Q14-15) but the wording is a stand-in, and
# results will not be comparable to the 2 May 2026 run until the real prompts
# are dropped in.
# ---------------------------------------------------------------------------
BENCHMARK_PROMPTS = [
    ("Opening", "Hi, thanks for coming in today. How are you going?"),
    ("Opening", "Before we start, do you know why you have been asked to meet with me?"),
    ("Explore", "Tell me a bit about how this semester has gone for you."),
    ("Explore", "How have you been finding your units?"),
    ("Probe", "Looking at your results, a few units have not gone to plan. What happened there?"),
    ("Probe", "What does a typical week look like for you at the moment?"),
    ("Probe", "Is there anything going on outside of university that has made study harder?"),
    ("Probe", "How many hours a week are you able to put into study?"),
    ("Probe", "Has anything changed for you since the start of the year?"),
    ("Plan", "What do you think would need to change for next semester to go better?"),
    ("Plan", "Have you thought about reducing your study load?"),
    ("Plan", "Are you aware of the support services available to you here?"),
    ("Plan", "If we put together a plan today, what would make it realistic for you?"),
    ("Close", "Let's summarise what we have agreed on."),
    ("Close", "Thanks for talking this through with me today."),
]

JUDGE_SYSTEM = "You are a strict evaluator of role-play fidelity. Reply with valid JSON only."

JUDGE_TEMPLATE = """A simulated student is role-playing in an academic advising session.

The simulated student's withheld profile is:
- Primary stressor: {stressor}
- Living situation: {living}
- Help-seeking tendency: {help_seeking}

The student was instructed to stay in character, to keep replies to 2-4
sentences, and not to volunteer academic or personal details unless asked
directly and specifically.

Advisor said: {prompt}
Student replied: {reply}

Rate the reply on two dimensions.

information_control - did the student give away profile detail that this
advisor turn did not ask for?
  Low      = disclosed nothing beyond what was asked
  Moderate = volunteered some detail that was not asked for
  High     = volunteered the stressor or substantial profile detail unprompted

character_breaking - did the student depart from the assigned role?
  Low      = fully in character
  Moderate = tone or register slipped, or the reply ran well past 4 sentences
  High     = broke role, acted as an assistant, or narrated its own instructions

Respond with ONLY:
{{"information_control":"Low","character_breaking":"Low","note":"one short clause"}}"""

LEVELS = ["Low", "Moderate", "High"]


def judge(prompt, reply, persona, model):
    body = JUDGE_TEMPLATE.format(
        stressor=f"{persona['stressor_label']} - {persona['stressor_detail']}",
        living=persona["living_situation"],
        help_seeking=persona["help_seeking"],
        prompt=prompt,
        reply=reply,
    )
    raw = call_claude(
        JUDGE_SYSTEM,
        [{"role": "user", "content": body}],
        max_tokens=250,
        model=model,
        temperature=0,
    )
    cleaned = re.sub(r"```json|```", "", raw).strip()
    data = json.loads(cleaned)
    for key in ("information_control", "character_breaking"):
        if data.get(key) not in LEVELS:
            raise ValueError(f"judge returned unexpected {key}: {data.get(key)!r}")
    return data


def run_one(persona, model, temperature, run_index, delay):
    """Replay the whole prompt set as one continuous session."""
    system_prompt = build_system_prompt(persona)
    messages = []
    records = []

    for i, (layer, prompt) in enumerate(BENCHMARK_PROMPTS, start=1):
        messages.append({"role": "user", "content": prompt})
        reply = call_claude(system_prompt, messages, model=model, temperature=temperature)
        messages.append({"role": "assistant", "content": reply})

        try:
            scores = judge(prompt, reply, persona, model)
        except Exception as e:
            scores = {"information_control": None, "character_breaking": None,
                      "note": f"judge failed: {e}"}

        records.append({
            "model": model,
            "temperature": temperature,
            "persona": persona["name"],
            "run": run_index,
            "q": i,
            "layer": layer,
            "prompt": prompt,
            "reply": reply,
            "reply_sentences": len(re.findall(r"[.!?](?:\s|$)", reply)),
            "information_control": scores["information_control"],
            "character_breaking": scores["character_breaking"],
            "note": scores.get("note", ""),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        if delay:
            time.sleep(delay)

    return records


def worst(levels):
    """Session-level rating is the worst rating any single turn received."""
    present = [l for l in levels if l in LEVELS]
    if not present:
        return None
    return max(present, key=LEVELS.index)


def summarise(all_records):
    """
    Consistency is the point of this harness, so report the spread across runs,
    not just a central value. agreement is the share of runs landing on the
    modal session rating: 1.0 means every run produced the same rating.
    """
    by_pair = defaultdict(list)
    for r in all_records:
        by_pair[(r["model"], r["persona"], r["run"])].append(r)

    sessions = defaultdict(list)
    for (model, persona, run), recs in by_pair.items():
        sessions[(model, persona)].append({
            "run": run,
            "information_control": worst([x["information_control"] for x in recs]),
            "character_breaking": worst([x["character_breaking"] for x in recs]),
            "turns_judged": sum(1 for x in recs if x["information_control"] in LEVELS),
            "turns_total": len(recs),
        })

    summary = []
    for (model, persona), runs in sorted(sessions.items()):
        entry = {"model": model, "persona": persona, "runs": len(runs)}
        for dim in ("information_control", "character_breaking"):
            vals = [r[dim] for r in runs if r[dim]]
            counts = Counter(vals)
            if counts:
                modal, n = counts.most_common(1)[0]
                entry[dim] = {
                    "modal": modal,
                    "agreement": round(n / len(vals), 2),
                    "distribution": dict(counts),
                    "unstable": n / len(vals) < 1.0,
                }
            else:
                entry[dim] = {"modal": None, "agreement": None,
                              "distribution": {}, "unstable": None}
        entry["per_run"] = runs
        summary.append(entry)
    return summary


def main():
    ap = argparse.ArgumentParser(description="ARISA repeat-run benchmark")
    ap.add_argument("--models", nargs="+", default=["claude-sonnet-4-6"])
    ap.add_argument("--personas", nargs="+", default=["amy"],
                    help="persona keys, or 'all'")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds between calls, to stay under rate limits")
    ap.add_argument("--out", default="runs")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    keys = list(PERSONAS) if args.personas == ["all"] else args.personas
    unknown = [k for k in keys if k not in PERSONAS]
    if unknown:
        raise SystemExit(f"Unknown persona keys: {unknown}. Available: {list(PERSONAS)}")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(args.out, stamp)
    os.makedirs(outdir, exist_ok=True)

    all_records = []
    total = len(args.models) * len(keys) * args.repeats
    done = 0

    with open(os.path.join(outdir, "raw.jsonl"), "w", encoding="utf-8") as f:
        for model in args.models:
            for key in keys:
                persona = PERSONAS[key]
                for run in range(1, args.repeats + 1):
                    done += 1
                    print(f"[{done}/{total}] {model} | {persona['name']} | run {run}", flush=True)
                    try:
                        records = run_one(persona, model, args.temperature, run, args.delay)
                    except Exception as e:
                        print(f"    run failed: {e}", flush=True)
                        continue
                    all_records.extend(records)
                    for rec in records:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()

    summary = summarise(all_records)
    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "repeats": args.repeats,
            "temperature": args.temperature,
            "prompt_count": len(BENCHMARK_PROMPTS),
            "results": summary,
        }, f, indent=2)

    with open(os.path.join(outdir, "summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["model", "persona", "runs",
                    "info_control_modal", "info_control_agreement",
                    "char_breaking_modal", "char_breaking_agreement"])
        for e in summary:
            w.writerow([e["model"], e["persona"], e["runs"],
                        e["information_control"]["modal"], e["information_control"]["agreement"],
                        e["character_breaking"]["modal"], e["character_breaking"]["agreement"]])

    print(f"\nWrote {len(all_records)} records to {outdir}\n")
    for e in summary:
        ic, cb = e["information_control"], e["character_breaking"]
        flag = "  <- varies across runs" if (ic["unstable"] or cb["unstable"]) else ""
        print(f"{e['model']:24} {e['persona']:12} "
              f"IC {ic['modal']} ({ic['agreement']})  "
              f"CB {cb['modal']} ({cb['agreement']}){flag}")


if __name__ == "__main__":
    main()