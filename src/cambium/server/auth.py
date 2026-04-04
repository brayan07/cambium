"""JWT-based session authentication for the Cambium API."""

from __future__ import annotations

import os
import time

import jwt

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
