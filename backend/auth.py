"""
auth.py
───────
JWT authentication utilities for the FastAPI backend.

Provides:
  - create_token(username, role) → str
  - verify_token(token) → dict
  - get_current_user(request) → FastAPI dependency
  - require_roles(*roles) → FastAPI dependency factory
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status

# ── Secret key ───────────────────────────────────────────────────────────────

_flask_env = os.environ.get("FLASK_ENV", "development")
_secret = os.environ.get("JWT_SECRET")

if not _secret:
    if _flask_env == "development":
        _secret = secrets.token_hex(32)
        print(
            "[auth] WARNING: JWT_SECRET not set — using random dev secret. "
            "Set JWT_SECRET env var for production."
        )
    else:
        raise RuntimeError(
            "JWT_SECRET environment variable is required in production. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )

SECRET_KEY: str = _secret
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


# ── Token helpers ────────────────────────────────────────────────────────────

def create_token(username: str, role: str) -> str:
    """Create a signed JWT with username, role, and expiry."""
    payload = {
        "username": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and verify a JWT.  Raises HTTPException on failure."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


# ── FastAPI dependencies ─────────────────────────────────────────────────────

COOKIE_NAME = "ts_token"   # HttpOnly cookie name

def _extract_token(request: Request) -> Optional[str]:
    """Extract JWT from (in priority order):
       1. Authorization: Bearer <token>  — API clients
       2. HttpOnly cookie 'ts_token'     — browser clients (more secure)
       3. ?token= query param            — <img>/<video> src fallback
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie
    return request.query_params.get("token")


async def get_current_user(request: Request) -> dict:
    """FastAPI dependency — returns decoded JWT payload or raises 401."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing",
        )
    return verify_token(token)


async def get_optional_user(request: Request) -> Optional[dict]:
    """FastAPI dependency — returns decoded JWT or None (no 401)."""
    token = _extract_token(request)
    if not token:
        return None
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        # Token was provided but invalid — still reject
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def require_roles(*roles: str):
    """Factory that returns a FastAPI dependency enforcing role membership."""

    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied. Invalid role.",
            )
        return user

    return _check
