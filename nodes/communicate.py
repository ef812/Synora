from llm_client import chat

NO_DIAGNOSIS_RULE = "Do not state a specific diagnosis or most-likely cause — present possible related topics as a range of possibilities only, and give general guidance plus when to seek professional evaluation."

TONE_MAP = {
    "employee": "simple, warm, non-alarming language a non-medical person understands",
    "doctor": "precise clinical language with full detail, including severity signal, triage recommendation, and evidence",
    "individual": "simple, direct, and honest language for someone checking on their own health, without workplace framing",
    "employer": "aggregated, anonymized wellness language — no individual medical specifics",
}


def communicate(state: dict) -> dict:
    audience = state.get("audience", "employee")
    tone = TONE_MAP.get(audience, TONE_MAP["employee"])

    if state["intent"] == "factual":
        prompt = f"Answer this question in {tone}, using only this context:\n{state['context']}\n\nQuestion: {state['question']}\n\n{NO_DIAGNOSIS_RULE}"
    else:
        analysis = state["analysis"]
        prompt = f"""Communicate this analysis in {tone}.

Flagged patterns: {analysis['flagged_patterns']}
Possible related topics (present as a range, not a conclusion): {analysis['possible_related_topics']}
Severity: {analysis['severity_signal']}
Triage recommendation: {analysis['triage_recommendation']}
Recommendations: {[r['text'] for r in state['recommendations']]}

{NO_DIAGNOSIS_RULE}
"""

    raw = chat(prompt)
    state["response"] = raw
    return state