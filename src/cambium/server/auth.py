"""JWT-based session authentication for the Cambium API."""

from __future__ import annotations

import os
import time

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Server-scoped signing key — generated once at import, lives in memory.
# All sessions spawned by this server process can be validated.
# On server restart, old tokens become invalid (which is fine —
# old sessions are dead too since the server spawned them).
_SIGNING_KEY = os.urandom(32)


def create_session_token(routine_name: str, session_id: str) -> str:
    """Create a JWT encoding the routine and session identity."""
    payload = {
        "routine": routine_name,
        "session": session_id,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, _SIGNING_KEY, algorithm="HS256")


def verify_session_token(token: str) -> dict:
    """Verify and decode a session token.

    Returns the decoded payload with 'routine' and 'session' fields.
    Raises jwt.InvalidTokenError on failure.
    """
    return jwt.decode(token, _SIGNING_KEY, algorithms=["HS256"])


def authenticate(authorization: str | None) -> dict:
    """Validate JWT and return claims. Raises HTTPException on failure."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_session_token(token)
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


# --- UI token endpoint ---
#
# The UI is the human's direct interface — it needs to answer HITL requests
# without going through the interlocutor routine. We mint a dedicated token
# with routine="human" at server startup and hand it to the frontend via an
# unauthenticated boot endpoint.
#
# A routine could technically call this endpoint too, but (a) routines get
# their own tokens via normal session spawning, (b) abuse would be a clear
# violation of the documented API surface, and (c) this is a single-user
# local tool — the security boundary is accidental misuse, not adversarial.

router = APIRouter(prefix="/auth", tags=["auth"])

_UI_TOKEN = create_session_token("human", "ui")


class UITokenResponse(BaseModel):
    token: str


@router.get("/ui-token", response_model=UITokenResponse)
def get_ui_token() -> UITokenResponse:
    """Return the UI token. Called once by the frontend on load."""
    return UITokenResponse(token=_UI_TOKEN)
