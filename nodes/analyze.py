from llm_client import chat
import json

ANALYZE_PROMPT = """You are a medical pattern analyzer. You do NOT diagnose conditions and you
NEVER state what is most likely happening to this specific person.

Given the user's question and retrieved medical context, identify:
1. flagged_patterns: general symptom/health patterns mentioned (not diagnoses)
2. possible_related_topics: a SHORT LIST (2-5) of general topics/conditions the retrieved
   context associates with these patterns — presented as a range of possibilities, not a
   conclusion. Do not rank one as "most likely." Do not say this is what the person has.
3. supporting_evidence: which source IDs (e.g. src_0) support each pattern/topic
4. severity_signal: one of "low", "moderate", "high", "unknown"
5. triage_recommendation: one of "self_care", "see_doctor_soon", "seek_urgent_care" — based
   on how urgently this pattern typically warrants professional evaluation
{workplace_section}
  
   
Respond ONLY with valid JSON in this exact shape, nothing else:
{{
  "flagged_patterns": ["..."],
  "possible_related_topics": ["...", "..."],
  "supporting_evidence": ["src_0", "src_1"],
  "severity_signal": "low",
  "triage_recommendation": "self_care"
}}

Question: {question}

Context:
{context}
"""

WORKPLACE_SECTION_TEMPLATE = """
Workplace context for this user (use to inform framing only — e.g. favor
ergonomic, burnout, shift-work-sleep, or workload-related framing where
relevant; this is background, not something to diagnose from or quote back
verbatim):
- Job role: {job_role}
- Work schedule: {work_schedule}
- Self-reported stress factors (1-5 scale): workload={workload}, hours={hours}, physical_strain={physical_strain}
{checkin_trend}"""

MAX_RETRIES = 2


def _format_workplace_section(employee_context: dict | None) -> str:
    if not employee_context:
        return ""

    stress = employee_context.get("stress_factors") or {}
    checkins = employee_context.get("recent_checkins") or []

    checkin_trend = ""
    if checkins:
        lines = [
            f"  - {c['date']}: energy={c.get('energy')}, stress={c.get('stress')}, "
            f"sleep={c.get('sleep')}" + (f", noted: {c['new_symptoms']}" if c.get("new_symptoms") else "")
            for c in checkins
        ]
        checkin_trend = "Recent check-in history (most recent first):\n" + "\n".join(lines)

    return WORKPLACE_SECTION_TEMPLATE.format(
        job_role=employee_context.get("job_role") or "not specified",
        work_schedule=employee_context.get("work_schedule") or "not specified",
        workload=stress.get("workload", "n/a"),
        hours=stress.get("hours", "n/a"),
        physical_strain=stress.get("physical_strain", "n/a"),
        checkin_trend=checkin_trend,
    )


def analyze(state: dict) -> dict:
    workplace_section = _format_workplace_section(state.get("employee_context"))
    prompt = ANALYZE_PROMPT.format(
        question=state["question"],
        context=state["context"],
        workplace_section=workplace_section,
    )

    for attempt in range(MAX_RETRIES + 1):
        raw = chat(prompt, temperature=0.1)

        if raw.startswith("```"):
            raw = raw.strip("`").replace("json", "", 1).strip()

        try:
            parsed = json.loads(raw)
            state["analysis"] = parsed
            return state
        except json.JSONDecodeError:
            continue

    state["analysis"] = {
        "flagged_patterns": [],
        "possible_related_topics": [],
        "supporting_evidence": [],
        "severity_signal": "unknown",
        "triage_recommendation": "see_doctor_soon",
    }
    return state
