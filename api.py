import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from graph import graph
from logger_config import log_event

app = FastAPI(title="Synora API")

executor = ThreadPoolExecutor(max_workers=4)
REQUEST_TIMEOUT_SECONDS = 30


class ChatRequest(BaseModel):
    question: str
    audience: str = "individual"  # "employee" | "doctor" | "individual"


class ChatResponse(BaseModel):
    response: str
    severity_signal: str | None = None
    triage_recommendation: str | None = None
    emergency_type: str | None = None


def run_graph(question: str, audience: str) -> dict:
    initial_state = {
        "question": question,
        "audience": audience,
        "sensor_data": {},
        "intent": "",
        "emergency_type": None,
        "context": "",
        "sources": [],
        "pages": [],
        "analysis": None,
        "recommendations": [],
        "evidence_check_passed": True,
        "evidence_failures": [],
        "response": "",
    }
    return graph.invoke(initial_state)


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    start = time.time()

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if req.audience not in ("employee", "doctor", "individual"):
        raise HTTPException(status_code=400, detail="Invalid audience.")

    log_event("request_received", question=req.question, audience=req.audience)

    future = executor.submit(run_graph, req.question, req.audience)
    try:
        result = future.result(timeout=REQUEST_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        log_event("request_timeout", question=req.question, audience=req.audience)
        raise HTTPException(status_code=504, detail="Request took too long. Please try again.")
    except Exception as e:
        log_event("request_error", question=req.question, audience=req.audience, error=str(e))
        raise HTTPException(status_code=500, detail="Something went wrong processing your request.")

    duration = time.time() - start

    log_event(
        "request_completed",
        question=req.question,
        audience=req.audience,
        intent=result.get("intent"),
        emergency_type=result.get("emergency_type"),
        evidence_check_passed=result.get("evidence_check_passed"),
        duration_seconds=round(duration, 2),
    )

    analysis = result.get("analysis") or {}

    return ChatResponse(
        response=result["response"],
        severity_signal=analysis.get("severity_signal"),
        triage_recommendation=analysis.get("triage_recommendation"),
        emergency_type=result.get("emergency_type"),
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}