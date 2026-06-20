from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic(auto_error=False)


def api_key_required(request: Request) -> None:
    expected = os.getenv("BOOK_API_KEY", "").strip()
    if not expected:
        return

    supplied = request.headers.get("x-api-key") or request.headers.get("x_api_key")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")


def dashboard_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    username = os.getenv("BOOK_ADMIN_USERNAME", "").strip()
    password = os.getenv("BOOK_ADMIN_PASSWORD", "").strip()

    # Empty username/password deliberately means local/open mode.
    if not username and not password:
        return

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
