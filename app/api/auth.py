from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic(auto_error=False)

LOCAL_RUNTIME_MODES = {"local", "development", "test"}


def runtime_mode() -> str:
    return os.getenv("BOOK_SYSTEM_ENV", "production").strip().lower() or "production"


def local_auth_bypass_enabled() -> bool:
    return runtime_mode() in LOCAL_RUNTIME_MODES


def configuration_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
    )


def api_key_required(request: Request) -> None:
    expected = os.getenv("BOOK_API_KEY", "").strip()
    if not expected:
        if local_auth_bypass_enabled():
            return
        raise configuration_error("API authentication is not configured")

    supplied = request.headers.get("x-api-key") or request.headers.get("x_api_key")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")


def dashboard_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    username = os.getenv("BOOK_ADMIN_USERNAME", "").strip()
    password = os.getenv("BOOK_ADMIN_PASSWORD", "").strip()

    if not username and not password:
        if local_auth_bypass_enabled():
            return
        raise configuration_error("Dashboard authentication is not configured")

    if not username or not password:
        raise configuration_error("Dashboard authentication is incomplete")

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    ok_user = secrets.compare_digest(credentials.username, username)
    ok_pass = secrets.compare_digest(credentials.password, password)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
