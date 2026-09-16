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
from clerk_backend_api.security import authenticate_request, AuthenticateRequestOptions
from sqlalchemy.orm import Session
import stripe
from config import (
    APP_API_KEY, CLERK_SECRET_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_MONTHLY, STRIPE_PRICE_ANNUAL, FRONTEND_URL, DOWNLOAD_URL_VALID_SECONDS,
    DESKTOP_TOKEN_SECRET,
)
from desktop_auth import create_desktop_token, verify_desktop_token, secret_fingerprint, debug_decode_desktop_token
from graph import graph
from logger_config import log_event
from nodes.document_ingest import ingest_document
from db import get_db
from models import EmployeeProfile, CheckinEntry
from b2_client import get_installer_download_url

stripe.api_key = STRIPE_SECRET_KEY

app = FastAPI(title="Synora API")

# Schema is now managed by Alembic migrations (see alembic/), not create_all().
# Run `alembic upgrade head` as part of your deploy process instead.

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    # "app://bundle" is the packaged Electron desktop app's origin (see
    # main.js's app:// protocol handler) -- without it, every fetch call the
    # desktop app makes to this backend fails CORS preflight, which is why
    # subscription status, employee profile, checkout, and chat all broke
    # at once after switching off raw file:// loading.
    allow_origins=["http://localhost:5173", "https://synora-frontend-swart.vercel.app", "app://bundle"],
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


def verify_clerk_user(request: Request):
    try:
        request_state = authenticate_request(
            request,
            AuthenticateRequestOptions(
                secret_key=CLERK_SECRET_KEY,
                authorized_parties=[
                    "http://localhost:5173",
                    "https://synora-frontend-swart.vercel.app",
                    "app://bundle",  # packaged Electron desktop app's origin
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


def get_current_user_id_flexible(request: Request) -> str:
    """Accepts either our own signed desktop token (desktop app calls,
    minted via /api/auth/desktop-handoff after a one-time Clerk sign-in in
    the system browser) or a real Clerk session (web tier calls). The
    desktop app never relies on Clerk's own getToken()/session refresh for
    authenticated API calls -- that's what kept 401ing under Electron's
    app:// origin. See desktop_auth.py for why.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        desktop_user_id = verify_desktop_token(token, DESKTOP_TOKEN_SECRET)
        if desktop_user_id:
            return desktop_user_id
        # TEMPORARY -- log exactly why this token failed, without exposing
        # the secret itself, to find whether it's a secret mismatch or
        # something else (e.g. token corrupted in transit).
        log_event("desktop_token_rejected", **debug_decode_desktop_token(token, DESKTOP_TOKEN_SECRET))
        # Not a valid/current desktop token -- fall through and try it as a
        # Clerk session token instead, rather than failing immediately.

    try:
        request_state = authenticate_request(
            request,
            AuthenticateRequestOptions(
                secret_key=CLERK_SECRET_KEY,
                authorized_parties=[
                    "http://localhost:5173",
                    "https://synora-frontend-swart.vercel.app",
                ],
                clock_skew_in_ms=15000,
            ),
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or missing session token.")

    if not request_state.is_signed_in:
        raise HTTPException(status_code=401, detail="You must be signed in to use this.")

    user_id = request_state.payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Could not determine user identity.")
    return user_id


class DesktopHandoffResponse(BaseModel):
    token: str


@app.post("/api/auth/desktop-handoff", response_model=DesktopHandoffResponse,
          dependencies=[Depends(verify_api_key)])
def desktop_handoff(user_id: str = Depends(get_current_user_id)):
    """Called from the web frontend (real https origin, where Clerk's normal
    sign-in flow works) once the user is signed in there. Mints our own
    signed desktop token (see desktop_auth.py) that the desktop app stores
    and uses as a plain Bearer token for every subsequent API call, handed
    over via the synora://auth deep link. Requiring Depends(get_current_user_id)
    here (Clerk-only, not the flexible version) means only someone who just
    did a real Clerk sign-in on the web tier can mint one.
    """
    token = create_desktop_token(user_id, DESKTOP_TOKEN_SECRET)
    log_event("desktop_token_minted", user_id=user_id, secret_fingerprint=secret_fingerprint(DESKTOP_TOKEN_SECRET))
    return DesktopHandoffResponse(token=token)


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


class CheckoutRequest(BaseModel):
    plan: str  # "monthly" | "annual"
    client: str = "web"  # "web" | "desktop" -- desktop gets a custom-protocol redirect instead of an https:// one


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    status: str  # "inactive" | "active" | "past_due" | "canceled"
    plan: str | None


class DownloadLinkResponse(BaseModel):
    download_url: str
    expires_in_seconds: int


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


@app.post("/api/upload", dependencies=[Depends(verify_api_key), Depends(get_current_user_id_flexible)])
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
def chat(request: Request, req: ChatRequest, db: Session = Depends(get_db),
         user_id: str = Depends(get_current_user_id_flexible)):
    start = time.time()

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if req.audience not in ("employee", "doctor", "individual"):
        raise HTTPException(status_code=400, detail="Invalid audience.")

    employee_context = None
    if req.audience == "employee":
        employee_context = load_employee_context(user_id, db)

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


@app.post("/api/chat/stream", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
def chat_stream(request: Request, req: ChatRequest, db: Session = Depends(get_db),
                 user_id: str = Depends(get_current_user_id_flexible)):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if req.audience not in ("employee", "doctor", "individual"):
        raise HTTPException(status_code=400, detail="Invalid audience.")

    employee_context = None
    if req.audience == "employee":
        employee_context = load_employee_context(user_id, db)

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
    user_id: str = Depends(get_current_user_id_flexible),
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
    user_id: str = Depends(get_current_user_id_flexible),
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
    user_id: str = Depends(get_current_user_id_flexible),
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
    user_id: str = Depends(get_current_user_id_flexible),
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


@app.post("/api/billing/create-checkout-session", response_model=CheckoutResponse,
          dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
def create_checkout_session(
    request: Request,
    req: CheckoutRequest,
    user_id: str = Depends(get_current_user_id_flexible),
    db: Session = Depends(get_db),
):
    if req.plan not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="Invalid plan. Must be 'monthly' or 'annual'.")

    price_id = STRIPE_PRICE_MONTHLY if req.plan == "monthly" else STRIPE_PRICE_ANNUAL
    if not price_id:
        raise HTTPException(status_code=500, detail="Billing is not configured correctly.")

    # A profile might not exist yet if the user is subscribing before ever
    # filling in workplace context -- create a bare row so we have somewhere
    # to attach the Stripe customer/subscription IDs once the webhook fires.
    profile = db.get(EmployeeProfile, user_id)
    if profile is None:
        profile = EmployeeProfile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    if req.client not in ("web", "desktop"):
        raise HTTPException(status_code=400, detail="Invalid client. Must be 'web' or 'desktop'.")

    # Desktop checkout happens in the OS browser (see electron/main.js), so we
    # can't send it back to an https:// URL loaded inside the packaged app's
    # own window -- that would just replace the app with the web tier. Instead
    # redirect to a custom protocol the Electron app registers and intercepts.
    if req.client == "desktop":
        success_url = "synora://checkout?status=success"
        cancel_url = "synora://checkout?status=canceled"
    else:
        success_url = f"{FRONTEND_URL}/?checkout=success"
        cancel_url = f"{FRONTEND_URL}/?checkout=canceled"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            customer=profile.stripe_customer_id,  # None on first checkout; Stripe creates one
            client_reference_id=user_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": user_id, "plan": req.plan},
        )
    except stripe.error.StripeError as e:
        log_event("checkout_session_error", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Could not start checkout. Please try again.")

    log_event("checkout_session_created", user_id=user_id, plan=req.plan)

    return CheckoutResponse(checkout_url=session.url)


@app.get("/api/billing/subscription-status", response_model=SubscriptionStatusResponse,
         dependencies=[Depends(verify_api_key)])
def subscription_status(
    request: Request,
    user_id: str = Depends(get_current_user_id_flexible),
    db: Session = Depends(get_db),
):
    profile = db.get(EmployeeProfile, user_id)
    if profile is None:
        return SubscriptionStatusResponse(status="inactive", plan=None)

    return SubscriptionStatusResponse(status=profile.subscription_status, plan=profile.subscription_plan)


@app.post("/api/billing/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        log_event("stripe_webhook_invalid", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    event_type = event["type"]
    # event["data"]["object"] is a Stripe SDK StripeObject, not a plain dict --
    # it supports item access (data["x"]) but NOT dict methods like .get(),
    # which raises AttributeError. Convert once here so the .get() calls below
    # (including nested "metadata") work on real dicts.
    data = event["data"]["object"].to_dict()

    # checkout.session.completed fires once, right after successful payment --
    # this is where we learn the Stripe customer/subscription IDs for the first time.
    if event_type == "checkout.session.completed":
        user_id = data.get("client_reference_id") or data.get("metadata", {}).get("user_id")
        plan = data.get("metadata", {}).get("plan")
        profile = db.get(EmployeeProfile, user_id) if user_id else None
        if profile:
            profile.stripe_customer_id = data.get("customer")
            profile.stripe_subscription_id = data.get("subscription")
            profile.subscription_status = "active"
            profile.subscription_plan = plan
            db.commit()
            log_event("subscription_activated", user_id=user_id, plan=plan)

    # customer.subscription.updated/deleted cover renewals, plan changes,
    # payment failures, and cancellations over the subscription's lifetime.
    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        subscription_id = data.get("id")
        profile = (
            db.query(EmployeeProfile)
            .filter(EmployeeProfile.stripe_subscription_id == subscription_id)
            .first()
        )
        if profile:
            stripe_status = data.get("status")  # "active" | "past_due" | "canceled" | etc.
            profile.subscription_status = stripe_status if event_type.endswith("updated") else "canceled"
            db.commit()
            log_event("subscription_status_changed", user_id=profile.user_id, status=profile.subscription_status)

    return {"received": True}


def require_active_subscription(user_id: str = Depends(get_current_user_id_flexible), db: Session = Depends(get_db)) -> str:
    """Dependency for gating employee-tier-only resources (e.g. the future
    package download endpoint) behind an active Stripe subscription."""
    profile = db.get(EmployeeProfile, user_id)
    if profile is None or not profile.has_active_subscription():
        raise HTTPException(status_code=402, detail="An active employee-tier subscription is required.")
    return user_id


@app.get("/api/employee/download", response_model=DownloadLinkResponse,
         dependencies=[Depends(verify_api_key)])
@limiter.limit("5/minute")
def get_download_link(
    request: Request,
    platform: str,
    user_id: str = Depends(require_active_subscription),
):
    if platform not in ("win", "mac"):
        raise HTTPException(status_code=400, detail="platform must be 'win' or 'mac'.")

    try:
        url = get_installer_download_url(platform)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsupported platform.")
    except Exception as e:
        log_event("download_link_error", user_id=user_id, platform=platform, error=str(e))
        raise HTTPException(status_code=500, detail="Could not generate download link. Please try again.")

    log_event("download_link_issued", user_id=user_id, platform=platform)

    return DownloadLinkResponse(download_url=url, expires_in_seconds=DOWNLOAD_URL_VALID_SECONDS)


@app.get("/api/health")
def health():
    return {"status": "ok"}
