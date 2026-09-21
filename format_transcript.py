"""
Format ARISA session JSON transcripts into clean Markdown appendix exhibits.
 
Usage:
    python format_transcript.py <session.json> [<session2.json> ...]
 
Produces one .md file per input, alongside the input file.
"""
import json
import sys
import os
 
 
def format_session(path):
    with open(path, "r", encoding="utf-8") as f:
        record = json.load(f)
 
    persona_name = record["persona"]["name"]
    sid = record["sid"]
    started = record.get("started_at", "unknown")
    ended = record.get("ended_at", "unknown")
    verify_log = record.get("verify_log", [])
 
    lines = []
    lines.append(f"# ARISA Session Transcript: {persona_name}")
    lines.append("")
    lines.append(f"**Session ID:** `{sid}`")
    lines.append(f"**Started:** {started}")
    lines.append(f"**Ended:** {ended}")
    lines.append(f"**Model:** {record.get('model', 'unknown')}")
    if record.get("abandoned"):
        lines.append(f"**Status:** Abandoned (no self-rating/debrief completed)")
    lines.append("")
    lines.append("---")
    lines.append("")
 
    messages = record.get("messages", [])
    assistant_turn_idx = 0
 
    for m in messages:
        role = m["role"]
        content = m["content"]
        if role == "user":
            lines.append(f"**Advisor:** {content}")
        else:
            lines.append(f"**{persona_name}:** {content}")
            if assistant_turn_idx < len(verify_log):
                attempts = verify_log[assistant_turn_idx]
                note = (
                    "passed first attempt"
                    if attempts == 0
                    else f"required {attempts} revision(s) after verifier flagged disclosure"
                )
                lines.append(f"*(verifier: {note})*")
            assistant_turn_idx += 1
        lines.append("")
 
    lines.append("---")
    lines.append("")
 
    if record.get("self_rating") is not None:
        lines.append(f"**Advisor self-rating:** {record['self_rating']}/7")
        lines.append("")
 
    elicitation = record.get("elicitation")
    if elicitation:
        lines.append("**Elicitation (debrief judge assessment):**")
        lines.append("")
        for item in elicitation:
            status = "Elicited" if item.get("elicited") else "Not elicited"
            lines.append(f"- **{item['attribute']}**: {status}")
            if item.get("evidence"):
                lines.append(f"  - Evidence: \"{item['evidence']}\"")
        lines.append("")
 
    return "\n".join(lines)
 
 
def main():
    if len(sys.argv) < 2:
        print("Usage: python format_transcript.py <session.json> [<session2.json> ...]")
        sys.exit(1)
 
    for path in sys.argv[1:]:
        if not os.path.exists(path):
            print(f"Skipping (not found): {path}")
            continue
        formatted = format_session(path)
        out_path = os.path.splitext(path)[0] + ".md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(formatted)
        print(f"Wrote: {out_path}")
 
 
if __name__ == "__main__":
    main()