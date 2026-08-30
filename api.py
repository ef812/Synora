import os
import time
import json
import shutil
import uuid
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from config import APP_API_KEY
from graph import graph
from logger_config import log_event
from nodes.document_ingest import ingest_document

app = FastAPI(title="Synora API")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://synora-frontend-swart.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)
REQUEST_TIMEOUT_SECONDS = 30

UPLOAD_DIR = "uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a moment and try again."},
    )


def verify_api_key(request: Request):
    key = request.headers.get("X-API-Key")
    if not APP_API_KEY or key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


class ChatRequest(BaseModel):
    question: str
    audience: str = "individual"  # "employee" | "doctor" | "individual"
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    severity_signal: str | None = None
    triage_recommendation: str | None = None
    emergency_type: str | None = None


def build_initial_state(question: str, audience: str, session_id: str | None = None) -> dict:
    return {
        "question": question,
        "audience": audience,
        "session_id": session_id,
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


def run_graph(question: str, audience: str, session_id: str | None = None) -> dict:
    return graph.invoke(build_initial_state(question, audience, session_id))


@app.post("/api/upload", dependencies=[Depends(verify_api_key)])
@limiter.limit("5/minute")
async def upload_document(request: Request, file: UploadFile = File(...), session_id: str = None):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    if not session_id:
        session_id = str(uuid.uuid4())

    filepath = os.path.join(UPLOAD_DIR, f"{session_id}_{file.filename}")
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        chunk_count = ingest_document(filepath, session_id)
    except Exception as e:
        log_event("upload_error", filename=file.filename, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process document.")

    log_event("document_uploaded", filename=file.filename, session_id=session_id, chunks=chunk_count)

    return {"session_id": session_id, "filename": file.filename, "chunks_added": chunk_count}


@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
def chat(request: Request, req: ChatRequest):
    start = time.time()

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if req.audience not in ("employee", "doctor", "individual"):
        raise HTTPException(status_code=400, detail="Invalid audience.")

    log_event("request_received", question=req.question, audience=req.audience)

    future = executor.submit(run_graph, req.question, req.audience, req.session_id)
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


@app.post("/api/chat/stream", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
def chat_stream(request: Request, req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if req.audience not in ("employee", "doctor", "individual"):
        raise HTTPException(status_code=400, detail="Invalid audience.")

    log_event("stream_request_received", question=req.question, audience=req.audience)

    initial_state = build_initial_state(req.question, req.audience, req.session_id)

    def event_generator():
        start = time.time()
        try:
            for step_output in graph.stream(initial_state):
                node_name = list(step_output.keys())[0]
                node_state = step_output[node_name]

                payload = {
                    "step": node_name,
                    "response": node_state.get("response"),
                    "analysis": node_state.get("analysis"),
                    "recommendations": node_state.get("recommendations"),
                    "emergency_type": node_state.get("emergency_type"),
                    "sources": node_state.get("sources"),
                }
                yield f"data: {json.dumps(payload)}\n\n"

            log_event(
                "stream_request_completed",
                question=req.question,
                audience=req.audience,
                duration_seconds=round(time.time() - start, 2),
            )
        except Exception as e:
            log_event("stream_request_error", question=req.question, audience=req.audience, error=str(e))
            yield f"data: {json.dumps({'step': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/health")
def health():
    return {"status": "ok"}
