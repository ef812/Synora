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


def analyze(state: dict) -> dict:
    prompt = ANALYZE_PROMPT.format(question=state["question"], context=state["context"])
    raw = chat(prompt)

    if raw.startswith("```"):
        raw = raw.strip("`").replace("json", "", 1).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "flagged_patterns": [],
            "possible_related_topics": [],
            "supporting_evidence": [],
            "severity_signal": "unknown",
            "triage_recommendation": "see_doctor_soon",
        }

    state["analysis"] = parsed
    return state