from llm_client import chat
import json

RECOMMEND_PROMPT = """You are a health recommendation generator. Base recommendations ONLY on
the flagged patterns, possible related topics, and supporting evidence below.

IMPORTANT RULES:
- Do NOT state or imply a specific diagnosis or "most likely cause."
- Do NOT present any single possible_related_topic as what is actually happening to this person.
- Only give general, non-diagnostic guidance: self-care steps, what to monitor, and when to
  seek professional evaluation.
- Do not add outside knowledge beyond what's given below.

Flagged patterns: {patterns}
Possible related topics (a range, not a conclusion): {topics}
Triage recommendation: {triage}
Supporting evidence source IDs: {evidence}

Context:
{context}

Respond ONLY with valid JSON, a list of recommendation objects, each with "text" and "source_ids":
[{{"text": "...", "source_ids": ["src_0"]}}]
"""


def recommend(state: dict) -> dict:
    analysis = state["analysis"]
    prompt = RECOMMEND_PROMPT.format(
        patterns=analysis.get("flagged_patterns", []),
        topics=analysis.get("possible_related_topics", []),
        triage=analysis.get("triage_recommendation", "see_doctor_soon"),
        evidence=analysis.get("supporting_evidence", []),
        context=state["context"],
    )
    raw = chat(prompt)
    print("---- RAW RECOMMEND OUTPUT ----")
    print(raw)
    print("-------------------------------")

    if raw.startswith("```"):
        raw = raw.strip("`").replace("json", "", 1).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = []

    state["recommendations"] = parsed
    return state