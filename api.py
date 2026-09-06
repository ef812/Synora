import os
import time
import json
import shutil
import uuid
from datetime import datetime, timezone
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
from clerk_backend_api import Clerk
from clerk_backend_api.security import authenticate_request, AuthenticateRequestOptions
from sqlalchemy.orm import Session
from config import APP_API_KEY, CLERK_SECRET_KEY
from graph import graph
from logger_config import log_event
from nodes.document_ingest import ingest_document
from db import get_db, init_db
from models import EmployeeProfile, CheckinEntry

app = FastAPI(title="Synora API")


@app.on_event("startup")
def on_startup():
    init_db()

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

clerk_client = Clerk(bearer_auth=CLERK_SECRET_KEY)


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


def verify_clerk_user(request: Request):
    try:
        request_state = authenticate_request(
            request,
            AuthenticateRequestOptions(
                secret_key=CLERK_SECRET_KEY,
                authorized_parties=[
                    "http://localhost:5173",
                    "https://synora-frontend-swart.vercel.app",
                ],
                clock_skew_in_ms=15000,  # 15 seconds, temporarily generous for local testing
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid or missing session token.")

    if not request_state.is_signed_in:
        raise HTTPException(status_code=401, detail="You must be signed in to use this.")

    return request_state.payload  # contains user info (e.g. user_id) if needed downstream


def get_current_user_id(payload: dict = Depends(verify_clerk_user)) -> str:
    """Clerk's JWT payload uses the standard 'sub' claim for the user id."""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Could not determine user identity.")
    return user_id


class ChatRequest(BaseModel):
    question: str
    audience: str = "individual"  # "employee" | "doctor" | "individual"
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    severity_signal: str | None = None
    triage_recommendation: str | None = None
    emergency_type: str | None = None


class StressFactors(BaseModel):
    workload: int = 3
    hours: int = 3
    physical_strain: int = 3


class EmployeeProfileRequest(BaseModel):
    job_role: str | None = None
    work_schedule: str | None = None  # "standard" | "shift" | "remote" | "hybrid"
    stress_factors: StressFactors | None = None
    checkin_interval_days: int = 7


class EmployeeProfileResponse(BaseModel):
    job_role: str | None
    work_schedule: str | None
    stress_factors: dict
    checkin_interval_days: int
    context_last_updated: str
    context_stale: bool


class CheckinRequest(BaseModel):
    energy: int | None = None  # 1-5
    stress: int | None = None  # 1-5
    sleep: int | None = None   # 1-5
    new_symptoms: str | None = None


class CheckinResponse(BaseModel):
    id: str
    created_at: str
    energy: int | None
    stress: int | None
    sleep: int | None
    new_symptoms: str | None


def build_initial_state(question: str, audience: str, session_id: str | None = None,
                         employee_context: dict | None = None) -> dict:
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
        "employee_context": employee_context,  # None unless audience == "employee"
    }


def load_employee_context(user_id: str, db: Session) -> dict | None:
    """Pulls workplace profile + recent check-in trend for the analyze prompt.
    Returns None if the user hasn't set up a profile -- employee audience
    still works, it just won't get the extra workplace framing."""
    profile = db.get(EmployeeProfile, user_id)
    if profile is None:
        return None

    recent_checkins = (
        db.query(CheckinEntry)
        .filter(CheckinEntry.user_id == user_id)
        .order_by(CheckinEntry.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "job_role": profile.job_role,
        "work_schedule": profile.work_schedule,
        "stress_factors": profile.stress_factors,
        "recent_checkins": [
            {
                "energy": c.energy, "stress": c.stress, "sleep": c.sleep,
                "new_symptoms": c.new_symptoms, "date": c.created_at.date().isoformat(),
            }
            for c in recent_checkins
        ],
    }


def run_graph(question: str, audience: str, session_id: str | None = None,
              employee_context: dict | None = None) -> dict:
    return graph.invoke(build_initial_state(question, audience, session_id, employee_context))


@app.post("/api/upload", dependencies=[Depends(verify_api_key), Depends(verify_clerk_user)])
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


@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key), Depends(verify_clerk_user)])
@limiter.limit("10/minute")
def chat(request: Request, req: ChatRequest, db: Session = Depends(get_db),
         payload: dict = Depends(verify_clerk_user)):
    start = time.time()

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if req.audience not in ("employee", "doctor", "individual"):
        raise HTTPException(status_code=400, detail="Invalid audience.")

    employee_context = None
    if req.audience == "employee":
        employee_context = load_employee_context(payload.get("sub"), db)

    log_event("request_received", question=req.question, audience=req.audience)

    future = executor.submit(run_graph, req.question, req.audience, req.session_id, employee_context)
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
        evidence_failures=result.get("evidence_failures"),
        duration_seconds=round(duration, 2),
    )

    analysis = result.get("analysis") or {}

    return ChatResponse(
        response=result["response"],
        severity_signal=analysis.get("severity_signal"),
        triage_recommendation=analysis.get("triage_recommendation"),
        emergency_type=result.get("emergency_type"),
    )


@app.post("/api/chat/stream", dependencies=[Depends(verify_api_key), Depends(verify_clerk_user)])
@limiter.limit("10/minute")
def chat_stream(request: Request, req: ChatRequest, db: Session = Depends(get_db),
                 payload: dict = Depends(verify_clerk_user)):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if req.audience not in ("employee", "doctor", "individual"):
        raise HTTPException(status_code=400, detail="Invalid audience.")

    employee_context = None
    if req.audience == "employee":
        employee_context = load_employee_context(payload.get("sub"), db)

    log_event("stream_request_received", question=req.question, audience=req.audience)

    initial_state = build_initial_state(req.question, req.audience, req.session_id, employee_context)

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


@app.post("/api/employee/profile", response_model=EmployeeProfileResponse,
          dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
def upsert_employee_profile(
    request: Request,
    req: EmployeeProfileRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    profile = db.get(EmployeeProfile, user_id)
    stress_factors = (req.stress_factors or StressFactors()).model_dump()

    if profile is None:
        profile = EmployeeProfile(
            user_id=user_id,
            job_role=req.job_role,
            work_schedule=req.work_schedule,
            stress_factors=stress_factors,
            checkin_interval_days=req.checkin_interval_days,
        )
        db.add(profile)
    else:
        profile.job_role = req.job_role
        profile.work_schedule = req.work_schedule
        profile.stress_factors = stress_factors
        profile.checkin_interval_days = req.checkin_interval_days
        profile.context_last_updated = datetime.now(timezone.utc)

    db.commit()
    db.refresh(profile)

    log_event("employee_profile_updated", user_id=user_id)

    return EmployeeProfileResponse(
        job_role=profile.job_role,
        work_schedule=profile.work_schedule,
        stress_factors=profile.stress_factors,
        checkin_interval_days=profile.checkin_interval_days,
        context_last_updated=profile.context_last_updated.isoformat(),
        context_stale=profile.context_is_stale(),
    )


@app.get("/api/employee/profile", response_model=EmployeeProfileResponse,
         dependencies=[Depends(verify_api_key)])
def get_employee_profile(
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    profile = db.get(EmployeeProfile, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No workplace profile set up yet.")

    return EmployeeProfileResponse(
        job_role=profile.job_role,
        work_schedule=profile.work_schedule,
        stress_factors=profile.stress_factors,
        checkin_interval_days=profile.checkin_interval_days,
        context_last_updated=profile.context_last_updated.isoformat(),
        context_stale=profile.context_is_stale(),
    )


@app.post("/api/employee/checkin", response_model=CheckinResponse,
          dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
def submit_checkin(
    request: Request,
    req: CheckinRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    profile = db.get(EmployeeProfile, user_id)
    if profile is None:
        raise HTTPException(status_code=400, detail="Set up your workplace profile before checking in.")

    entry = CheckinEntry(
        user_id=user_id,
        energy=req.energy,
        stress=req.stress,
        sleep=req.sleep,
        new_symptoms=req.new_symptoms,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    log_event("checkin_submitted", user_id=user_id, energy=req.energy, stress=req.stress, sleep=req.sleep)

    return CheckinResponse(
        id=entry.id,
        created_at=entry.created_at.isoformat(),
        energy=entry.energy,
        stress=entry.stress,
        sleep=entry.sleep,
        new_symptoms=entry.new_symptoms,
    )


@app.get("/api/employee/checkin/history", response_model=list[CheckinResponse],
         dependencies=[Depends(verify_api_key)])
def checkin_history(
    request: Request,
    limit: int = 10,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(CheckinEntry)
        .filter(CheckinEntry.user_id == user_id)
        .order_by(CheckinEntry.created_at.desc())
        .limit(min(limit, 50))
        .all()
    )
    return [
        CheckinResponse(
            id=e.id,
            created_at=e.created_at.isoformat(),
            energy=e.energy,
            stress=e.stress,
            sleep=e.sleep,
            new_symptoms=e.new_symptoms,
        )
        for e in entries
    ]


@app.get("/api/health")
def health():
    return {"status": "ok"}
