ANALYSIS_KEYWORDS = [
    "feel", "pain", "symptom", "tired", "hurts", "dizzy",
    "sleep", "stress", "posture", "heart rate", "recommend",
    "should i", "is it normal", "worried about"
]


def classify_intent(state: dict) -> dict:
    question = state["question"].lower()
    needs_analysis = any(kw in question for kw in ANALYSIS_KEYWORDS)
    state["intent"] = "analysis_needed" if needs_analysis else "factual"
    return state