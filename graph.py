from langgraph.graph import StateGraph, END
from state import SynoraState
from nodes.classify_intent import classify_intent
from nodes.emergency_check import check_emergency
from nodes.emergency_response import emergency_response
from nodes.retrieve import retrieve
from nodes.analyze import analyze
from nodes.verify_evidence import verify_analysis_evidence, verify_recommendation_evidence
from nodes.recommend import recommend
from nodes.communicate import communicate
from nodes.fallback import flag_insufficient_evidence


def route_after_emergency_check(state: dict) -> str:
    return "emergency_response" if state["emergency_type"] else "retrieve"


def route_after_retrieve(state: dict) -> str:
    return "analyze" if state["intent"] == "analysis_needed" else "communicate"


def route_after_analysis_check(state: dict) -> str:
    return "recommend" if state["evidence_check_passed"] else "fallback"


def route_after_recommend_check(state: dict) -> str:
    return "communicate" if state["evidence_check_passed"] else "fallback"


builder = StateGraph(SynoraState)

builder.add_node("classify_intent", classify_intent)
builder.add_node("check_emergency", check_emergency)
builder.add_node("emergency_response", emergency_response)
builder.add_node("retrieve", retrieve)
builder.add_node("analyze", analyze)
builder.add_node("verify_analysis_evidence", verify_analysis_evidence)
builder.add_node("recommend", recommend)
builder.add_node("verify_recommendation_evidence", verify_recommendation_evidence)
builder.add_node("communicate", communicate)
builder.add_node("fallback", flag_insufficient_evidence)

builder.set_entry_point("classify_intent")
builder.add_edge("classify_intent", "check_emergency")

builder.add_conditional_edges("check_emergency", route_after_emergency_check, {
    "emergency_response": "emergency_response",
    "retrieve": "retrieve",
})
builder.add_edge("emergency_response", END)

builder.add_conditional_edges("retrieve", route_after_retrieve, {
    "analyze": "analyze",
    "communicate": "communicate",
})
builder.add_edge("analyze", "verify_analysis_evidence")
builder.add_conditional_edges("verify_analysis_evidence", route_after_analysis_check, {
    "recommend": "recommend",
    "fallback": "fallback",
})
builder.add_edge("recommend", "verify_recommendation_evidence")
builder.add_conditional_edges("verify_recommendation_evidence", route_after_recommend_check, {
    "communicate": "communicate",
    "fallback": "fallback",
})
builder.add_edge("communicate", END)
builder.add_edge("fallback", END)

graph = builder.compile()