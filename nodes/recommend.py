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
- For source_ids, you MUST only use IDs from this exact list, copied verbatim: {valid_sources}.
  Never invent an ID that isn't in that list, and never cite an ID whose content doesn't
  actually support the recommendation you're attaching it to. If no ID genuinely supports a
  recommendation, give it an empty source_ids list rather than guessing.

Flagged patterns: {patterns}
Possible related topics (a range, not a conclusion): {topics}
Triage recommendation: {triage}
Supporting evidence source IDs: {evidence}

Context:
{context}

Respond ONLY with valid JSON, a list of recommendation objects, each with "text" and "source_ids":
[{{"text": "...", "source_ids": ["src_0"]}}]
"""

MAX_RETRIES = 2


def recommend(state: dict) -> dict:
    analysis = state["analysis"]
    prompt = RECOMMEND_PROMPT.format(
        patterns=analysis.get("flagged_patterns", []),
        topics=analysis.get("possible_related_topics", []),
        triage=analysis.get("triage_recommendation", "see_doctor_soon"),
        evidence=analysis.get("supporting_evidence", []),
        context=state["context"],
        valid_sources=", ".join(state["sources"]) if state["sources"] else "(none retrieved)",
    )

    for attempt in range(MAX_RETRIES + 1):
        raw = chat(prompt, temperature=0.1)

        if raw.startswith("```"):
            raw = raw.strip("`").replace("json", "", 1).strip()

        try:
            parsed = json.loads(raw)
            state["recommendations"] = parsed
            return state
        except json.JSONDecodeError:
            continue

    state["recommendations"] = []
    return state
