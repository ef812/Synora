"""Signed tokens for the desktop app's authenticated API calls.

Why this exists: the desktop app runs its renderer from a custom app://
origin (see electron/main.js), and Clerk's own browser session/cookie
persistence + silent refresh doesn't work reliably there -- getToken()
calls were coming back invalid, causing every authenticated endpoint to
401 even right after a successful sign-in.

Instead, the desktop app authenticates with Clerk exactly once, in the
system browser (a real https origin -- see DesktopAuthHandoff.jsx on the
web frontend), and the backend hands back one of these self-contained
signed tokens via the synora://auth deep link. From then on, the desktop
app sends this as a plain Bearer token on every request; it never calls
Clerk's own APIs for authenticated requests again. The web tier is
completely unaffected -- it keeps using Clerk's normal session flow.

Deliberately stdlib-only (hmac/hashlib/base64), no new dependency, and no
database table -- the token is self-verifying. Trade-off: it can't be
revoked before it expires short of rotating DESKTOP_TOKEN_SECRET (which
would invalidate every issued token, not just one). Keep the TTL modest
for that reason.
"""

import base64
import hashlib
import hmac
import time


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_desktop_token(user_id: str, secret: str, ttl_seconds: int = 60 * 60 * 24 * 14) -> str:
    """14-day default TTL -- long enough that desktop users aren't forced to
    re-authenticate constantly, short enough to bound the un-revocability
    trade-off above. The desktop app re-runs the browser handoff whenever
    a request comes back 401 due to expiry (see App.jsx)."""
    expires_at = int(time.time()) + ttl_seconds
    payload = f"{user_id}:{expires_at}"
    signature = _sign(payload, secret)
    raw = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_desktop_token(token: str, secret: str) -> str | None:
    """Returns the user_id if the token is well-formed, correctly signed,
    and not expired -- otherwise None (never raises, so callers can cleanly
    fall through to trying a Clerk session instead)."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, expires_at_str, signature = raw.rsplit(":", 2)
        expires_at = int(expires_at_str)
    except Exception:
        return None

    expected_signature = _sign(f"{user_id}:{expires_at}", secret)
    if not hmac.compare_digest(signature, expected_signature):
        return None
    if expires_at < int(time.time()):
        return None
    return user_id


def secret_fingerprint(secret: str | None) -> str:
    """A short, non-reversible fingerprint of the secret currently in use --
    safe to log. If the mint-time and verify-time fingerprints differ, the
    secret itself is inconsistent between requests (e.g. Railway env var
    changed/rolled back between deploys); if they match, the bug is
    elsewhere (e.g. the Authorization header not reaching the backend).
    TEMPORARY -- remove once the 401 issue is resolved."""
    if not secret:
        return "MISSING"
    return hashlib.sha256(secret.encode()).hexdigest()[:8]


def debug_decode_desktop_token(token: str, secret: str) -> dict:
    """Diagnostic-only decode that reports *why* verification failed,
    without ever exposing the secret itself. TEMPORARY -- remove once the
    401 issue is resolved."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, expires_at_str, signature = raw.rsplit(":", 2)
        expires_at = int(expires_at_str)
    except Exception as e:
        return {"decode_error": str(e)}

    expected_signature = _sign(f"{user_id}:{expires_at}", secret)
    return {
        "user_id": user_id,
        "expires_at": expires_at,
        "expired": expires_at < int(time.time()),
        "signature_matches": hmac.compare_digest(signature, expected_signature),
        "secret_fingerprint": secret_fingerprint(secret),
    }
