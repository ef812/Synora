def flag_insufficient_evidence(state: dict) -> dict:
    state["response"] = (
        "I don't have strong enough evidence in the retrieved medical sources to answer this "
        "confidently. Please consult a healthcare professional, or try rephrasing your question."
    )
    return state