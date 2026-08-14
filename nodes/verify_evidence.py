def verify_analysis_evidence(state: dict) -> dict:
    valid_sources = set(state["sources"])
    cited = set(state["analysis"].get("supporting_evidence", []))
    invalid = cited - valid_sources

    state["evidence_check_passed"] = len(invalid) == 0
    state["evidence_failures"] = list(invalid)
    return state


def verify_recommendation_evidence(state: dict) -> dict:
    valid_sources = set(state["sources"])
    all_invalid = []

    for rec in state["recommendations"]:
        invalid = set(rec.get("source_ids", [])) - valid_sources
        all_invalid.extend(invalid)

    state["evidence_check_passed"] = len(all_invalid) == 0
    state["evidence_failures"] = all_invalid
    return state