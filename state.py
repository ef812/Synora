from typing import TypedDict, List, Dict, Optional


class Recommendation(TypedDict):
    text: str
    source_ids: List[str]


class Analysis(TypedDict):
    flagged_patterns: List[str]
    possible_related_topics: List[str]
    supporting_evidence: List[str]
    severity_signal: str  # "low" | "moderate" | "high" | "unknown"
    triage_recommendation: str  # "self_care" | "see_doctor_soon" | "seek_urgent_care"


class SynoraState(TypedDict):
    question: str
    audience: str  # "employee" | "doctor" | "individual"
    sensor_data: Dict
    intent: str  # "factual" | "analysis_needed"
    emergency_type: Optional[str]  # "physical" | "crisis" | None
    context: str
    sources: List[str]
    pages: List[int]
    analysis: Optional[Analysis]
    recommendations: List[Recommendation]
    evidence_check_passed: bool
    evidence_failures: List[str]
    response: str