from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.services.security import (
    SecurityAuditError,
    SecurityConfigError,
    authentication_is_blocked,
    clear_authentication_failures,
    configured_value,
    local_runtime_mode,
    record_security_event,
    register_authentication_failure,
    security_config,
)

security = HTTPBasic(auto_error=False)


def configuration_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
    )


def _security_unavailable(exc: Exception) -> HTTPException:
    return configuration_error(str(exc))


def _rate_limit_exception(retry_after: int) -> HTTPException:
    seconds = max(1, int(retry_after))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Authentication rate limit exceeded",
        headers={"Retry-After": str(seconds)},
    )


def _check_authentication_rate_limit(request: Request, auth_kind: str) -> None:
    try:
        blocked, retry_after = authentication_is_blocked(request, auth_kind)
        if not blocked:
            return
        config = security_config()
        record_security_event(
            "authentication.rate-limit",
            "refused",
            details={
                "auth_kind": auth_kind,
                "limit": config.auth_failure_limit,
                "window_seconds": config.auth_failure_window_seconds,
            },
        )
    except (SecurityConfigError, SecurityAuditError) as exc:
        raise _security_unavailable(exc) from exc

    raise _rate_limit_exception(retry_after)


def _reject_authentication(
    request: Request,
    *,
    auth_kind: str,
    reason_code: str,
    status_code: int,
    detail: str,
    headers: dict[str, str] | None = None,
) -> None:
    try:
        blocked, retry_after = register_authentication_failure(
            request,
            auth_kind,
            reason_code,
        )
    except (SecurityConfigError, SecurityAuditError) as exc:
        raise _security_unavailable(exc) from exc

    if blocked:
        raise _rate_limit_exception(retry_after)

    raise HTTPException(
        status_code=status_code,
        detail=detail,
        headers=headers,
    )


def api_key_required(request: Request) -> None:
    expected = os.getenv("BOOK_API_KEY", "").strip()
    if not configured_value(expected):
        if local_runtime_mode():
            return
        raise configuration_error("API authentication is not configured")

    _check_authentication_rate_limit(request, "api-key")

    supplied = request.headers.get("x-api-key") or request.headers.get("x_api_key")
    if not supplied or not secrets.compare_digest(supplied, expected):
        _reject_authentication(
            request,
            auth_kind="api-key",
            reason_code="missing-or-invalid",
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized",
        )

    clear_authentication_failures(request, "api-key")


def dashboard_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> None:
    username = os.getenv("BOOK_ADMIN_USERNAME", "").strip()
    password = os.getenv("BOOK_ADMIN_PASSWORD", "").strip()

    username_configured = configured_value(username)
    password_configured = configured_value(password)

    if not username_configured and not password_configured:
        if local_runtime_mode():
            return
        raise configuration_error("Dashboard authentication is not configured")

    if not username_configured or not password_configured:
        raise configuration_error("Dashboard authentication is incomplete")

    _check_authentication_rate_limit(request, "basic")

    if credentials is None:
        _reject_authentication(
            request,
            auth_kind="basic",
            reason_code="missing",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    ok_user = secrets.compare_digest(credentials.username, username)
    ok_pass = secrets.compare_digest(credentials.password, password)
    if not (ok_user and ok_pass):
        _reject_authentication(
            request,
            auth_kind="basic",
            reason_code="invalid",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    clear_authentication_failures(request, "basic")
