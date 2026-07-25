from __future__ import annotations

import contextvars
import html
import ipaddress
import json
import math
import os
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.utils.paths import logs_dir

LOCAL_RUNTIME_MODES = {"local", "development", "test"}
PLACEHOLDER_PREFIXES = ("replace-with-", "change-this", "changeme")

DEFAULT_REQUEST_LIMIT = 120
DEFAULT_REQUEST_WINDOW_SECONDS = 60.0
DEFAULT_AUTH_FAILURE_LIMIT = 5
DEFAULT_AUTH_FAILURE_WINDOW_SECONDS = 300.0
DEFAULT_CSRF_COOKIE_SECONDS = 8 * 60 * 60
DEFAULT_RATE_LIMIT_MAX_KEYS = 2048

CSRF_COOKIE_NAME = "book_csrf"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
SECURITY_AUDIT_FILENAME = "security-events.jsonl"
BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
RATE_LIMIT_EXEMPT_PATHS = {"/health", "/ready", "/api/v1/status"}

_EVENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_FORM_RE = re.compile(
    r"<form\b(?=[^>]*\bmethod\s*=\s*[\"']post[\"'])[^>]*>",
    flags=re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_FORBIDDEN_DETAIL_PARTS = {
    "password",
    "secret",
    "token",
    "cookie",
    "authorization",
    "api_key",
    "apikey",
    "markdown",
    "content",
    "title",
}
_ALLOWED_DETAIL_KEYS = {
    "auth_kind",
    "reason_code",
    "limit",
    "window_seconds",
    "job_id",
    "state",
    "previous_state",
    "target_state",
    "older_than_days",
    "eligible_count",
    "archived_count",
    "dry_run",
    "retry_count",
    "recovery_target",
    "operator",
    "recovery_count",
}

_request_context: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "book_security_request_context",
    default={},
)
_csrf_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "book_security_csrf_token",
    default="",
)
_audit_lock = threading.Lock()


class SecurityConfigError(RuntimeError):
    """Raised when H-06 security configuration is invalid."""


class SecurityAuditError(RuntimeError):
    """Raised when a required security event cannot be recorded."""


@dataclass(frozen=True)
class SecurityConfig:
    csrf_enabled: bool
    rate_limit_enabled: bool
    audit_enabled: bool
    request_limit: int
    request_window_seconds: float
    auth_failure_limit: int
    auth_failure_window_seconds: float
    csrf_cookie_seconds: int
    max_rate_limit_keys: int


def runtime_mode() -> str:
    return os.getenv("BOOK_SYSTEM_ENV", "production").strip().lower() or "production"


def local_runtime_mode() -> bool:
    return runtime_mode() in LOCAL_RUNTIME_MODES


def configured_value(value: str) -> bool:
    normalised = value.strip().lower()
    return bool(normalised) and not normalised.startswith(PLACEHOLDER_PREFIXES)


def _bool_value(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalised = raw.strip().lower()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    raise SecurityConfigError(f"{name} must be true or false")


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SecurityConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise SecurityConfigError(f"{name} must be greater than zero")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SecurityConfigError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise SecurityConfigError(f"{name} must be greater than zero")
    return value


def security_config() -> SecurityConfig:
    production_default = not local_runtime_mode()
    return SecurityConfig(
        csrf_enabled=_bool_value("BOOK_SECURITY_CSRF_ENABLED", production_default),
        rate_limit_enabled=_bool_value(
            "BOOK_SECURITY_RATE_LIMIT_ENABLED",
            production_default,
        ),
        audit_enabled=_bool_value("BOOK_SECURITY_AUDIT_ENABLED", production_default),
        request_limit=_positive_int(
            "BOOK_SECURITY_REQUEST_LIMIT",
            DEFAULT_REQUEST_LIMIT,
        ),
        request_window_seconds=_positive_float(
            "BOOK_SECURITY_REQUEST_WINDOW_SECONDS",
            DEFAULT_REQUEST_WINDOW_SECONDS,
        ),
        auth_failure_limit=_positive_int(
            "BOOK_SECURITY_AUTH_FAILURE_LIMIT",
            DEFAULT_AUTH_FAILURE_LIMIT,
        ),
        auth_failure_window_seconds=_positive_float(
            "BOOK_SECURITY_AUTH_FAILURE_WINDOW_SECONDS",
            DEFAULT_AUTH_FAILURE_WINDOW_SECONDS,
        ),
        csrf_cookie_seconds=_positive_int(
            "BOOK_SECURITY_CSRF_COOKIE_SECONDS",
            DEFAULT_CSRF_COOKIE_SECONDS,
        ),
        max_rate_limit_keys=_positive_int(
            "BOOK_SECURITY_RATE_LIMIT_MAX_KEYS",
            DEFAULT_RATE_LIMIT_MAX_KEYS,
        ),
    )


class BoundedWindowLimiter:
    """Thread-safe in-memory sliding window with bounded key cardinality."""

    def __init__(self) -> None:
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _prune(bucket: deque[float], *, now: float, window_seconds: float) -> None:
        threshold = now - window_seconds
        while bucket and bucket[0] <= threshold:
            bucket.popleft()

    def _bucket(
        self,
        key: str,
        *,
        max_keys: int,
    ) -> deque[float]:
        bucket = self._buckets.get(key)
        if bucket is None:
            while len(self._buckets) >= max_keys:
                self._buckets.popitem(last=False)
            bucket = deque()
            self._buckets[key] = bucket
        else:
            self._buckets.move_to_end(key)
        return bucket

    def status(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        max_keys: int,
        now: float | None = None,
    ) -> tuple[int, float]:
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            bucket = self._bucket(key, max_keys=max_keys)
            self._prune(bucket, now=timestamp, window_seconds=window_seconds)
            if not bucket:
                return 0, 0.0
            retry_after = max(0.0, window_seconds - (timestamp - bucket[0]))
            return len(bucket), retry_after

    def add(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        max_keys: int,
        now: float | None = None,
    ) -> tuple[int, float]:
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            bucket = self._bucket(key, max_keys=max_keys)
            self._prune(bucket, now=timestamp, window_seconds=window_seconds)
            bucket.append(timestamp)
            retry_after = max(0.0, window_seconds - (timestamp - bucket[0]))
            return len(bucket), retry_after

    def clear(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_request_limiter = BoundedWindowLimiter()
_auth_failure_limiter = BoundedWindowLimiter()


def reset_security_state() -> None:
    """Reset process-local limiter state for focused tests."""

    _request_limiter.reset()
    _auth_failure_limiter.reset()


def _header_map(scope: dict[str, Any]) -> dict[bytes, bytes]:
    return {
        key.lower(): value
        for key, value in scope.get("headers", [])
    }


def _validated_ip(value: str) -> str | None:
    candidate = value.strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def client_address(scope: dict[str, Any]) -> str:
    client = scope.get("client")
    peer = "unknown"
    if isinstance(client, (tuple, list)) and client:
        peer = str(client[0])

    peer_ip = _validated_ip(peer)
    headers = _header_map(scope)
    forwarded = headers.get(b"x-forwarded-for")

    if peer_ip in {"127.0.0.1", "::1"} and forwarded:
        first = forwarded.decode("latin-1", errors="replace").split(",", 1)[0]
        forwarded_ip = _validated_ip(first)
        if forwarded_ip:
            return forwarded_ip

    return peer_ip or "unknown"


def _request_metadata(scope: dict[str, Any]) -> dict[str, str]:
    return {
        "method": str(scope.get("method", "")),
        "path": str(scope.get("path", ""))[:240],
        "client": client_address(scope),
    }


def _security_json_response(
    *,
    status_code: int,
    detail: str,
    code: str,
    retry_after: int | None = None,
) -> JSONResponse:
    headers: dict[str, str] = {}
    payload: dict[str, Any] = {"detail": detail, "code": code}
    if retry_after is not None:
        headers["Retry-After"] = str(max(1, int(retry_after)))
        payload["retry_after_seconds"] = max(1, int(retry_after))
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def _normalise_event(value: str) -> str:
    event = value.strip().lower()
    if not _EVENT_RE.fullmatch(event):
        raise SecurityAuditError("Security event name is invalid")
    return event


def _safe_detail_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 3)
    if value is None:
        return None
    return str(value)[:160]


def _sanitise_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}

    clean: dict[str, Any] = {}
    for key, value in details.items():
        normalised = str(key).strip().lower()
        if normalised not in _ALLOWED_DETAIL_KEYS:
            raise SecurityAuditError(f"Security audit detail is not allowlisted: {key}")
        if any(part in normalised for part in _FORBIDDEN_DETAIL_PARTS):
            raise SecurityAuditError(f"Security audit detail is forbidden: {key}")
        clean[normalised] = _safe_detail_value(value)
    return clean


def security_audit_path() -> Path:
    return logs_dir() / SECURITY_AUDIT_FILENAME


def record_security_event(
    event: str,
    outcome: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    config = security_config()
    if not config.audit_enabled:
        return

    event_name = _normalise_event(event)
    outcome_value = outcome.strip().lower()
    if outcome_value not in {"attempt", "authorised", "completed", "refused", "failed"}:
        raise SecurityAuditError("Security event outcome is invalid")

    context = dict(_request_context.get())
    payload: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event_name,
        "outcome": outcome_value,
        "method": context.get("method", ""),
        "path": context.get("path", ""),
        "client": context.get("client", "unknown"),
        "details": _sanitise_details(details),
    }
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    path = security_audit_path()

    try:
        with _audit_lock:
            fd = os.open(
                str(path),
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)
    except OSError as exc:
        raise SecurityAuditError("Security audit log is unavailable") from exc


def require_security_event(
    event: str,
    outcome: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        record_security_event(event, outcome, details=details)
    except (SecurityAuditError, SecurityConfigError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _auth_key(request: Request, auth_kind: str) -> str:
    return f"auth:{auth_kind}:{client_address(request.scope)}"


def authentication_is_blocked(
    request: Request,
    auth_kind: str,
) -> tuple[bool, int]:
    config = security_config()
    if not config.rate_limit_enabled:
        return False, 0

    count, retry_after = _auth_failure_limiter.status(
        _auth_key(request, auth_kind),
        limit=config.auth_failure_limit,
        window_seconds=config.auth_failure_window_seconds,
        max_keys=config.max_rate_limit_keys,
    )
    return count >= config.auth_failure_limit, max(1, math.ceil(retry_after))


def register_authentication_failure(
    request: Request,
    auth_kind: str,
    reason_code: str,
) -> tuple[bool, int]:
    config = security_config()
    count = 0
    retry_after = 0.0
    if config.rate_limit_enabled:
        count, retry_after = _auth_failure_limiter.add(
            _auth_key(request, auth_kind),
            limit=config.auth_failure_limit,
            window_seconds=config.auth_failure_window_seconds,
            max_keys=config.max_rate_limit_keys,
        )

    record_security_event(
        "authentication.failure",
        "refused",
        details={
            "auth_kind": auth_kind,
            "reason_code": reason_code,
            "limit": config.auth_failure_limit,
            "window_seconds": config.auth_failure_window_seconds,
        },
    )

    blocked = config.rate_limit_enabled and count >= config.auth_failure_limit
    return blocked, max(1, math.ceil(retry_after)) if blocked else 0


def clear_authentication_failures(request: Request, auth_kind: str) -> None:
    _auth_failure_limiter.clear(_auth_key(request, auth_kind))


def _valid_csrf_token(value: str | None) -> bool:
    return bool(value and _TOKEN_RE.fullmatch(value))


def current_csrf_token() -> str:
    return _csrf_context.get()


def inject_csrf_fields(document: str) -> str:
    token = current_csrf_token()
    if not token:
        return document

    field = (
        f'<input type="hidden" name="{CSRF_FORM_FIELD}" '
        f'value="{html.escape(token, quote=True)}">'
    )
    return _FORM_RE.sub(lambda match: match.group(0) + field, document)


def _csrf_cookie_header(token: str, *, max_age: int) -> bytes:
    response = Response()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path="/",
        secure=not local_runtime_mode(),
        httponly=True,
        samesite="strict",
    )
    for key, value in response.raw_headers:
        if key.lower() == b"set-cookie":
            return value
    raise RuntimeError("CSRF cookie header could not be created")


def _same_origin(request: Request) -> bool:
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return True

    parsed = urlsplit(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    expected_host = request.headers.get("host", "").strip().lower()
    return bool(expected_host) and parsed.netloc.lower() == expected_host


async def _read_body(
    receive: Callable[[], Awaitable[dict[str, Any]]],
) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            break
        if message.get("type") != "http.request":
            continue
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _replay_receive(body: bytes) -> Callable[[], Awaitable[dict[str, Any]]]:
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
        return {
            "type": "http.request",
            "body": b"",
            "more_body": False,
        }

    return receive


def _submitted_csrf_token(request: Request, body: bytes) -> str | None:
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if header_value:
        return header_value

    content_type = request.headers.get("content-type", "").lower()
    if "application/x-www-form-urlencoded" not in content_type:
        return None

    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return None
    values = fields.get(CSRF_FORM_FIELD)
    return values[0] if values else None


def _dashboard_surface(path: str) -> bool:
    return not path.startswith("/api/") and path not in RATE_LIMIT_EXEMPT_PATHS


class SecurityMiddleware:
    """Apply H-06 request rate limits and dashboard CSRF protection."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        try:
            config = security_config()
        except SecurityConfigError as exc:
            response = _security_json_response(
                status_code=503,
                detail=str(exc),
                code="invalid-security-config",
            )
            await response(scope, receive, send)
            return

        context_token = _request_context.set(_request_metadata(scope))
        csrf_context_token: contextvars.Token[str] | None = None
        request = Request(scope)
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        dashboard_surface = _dashboard_surface(path)
        cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
        valid_cookie = cookie_value if _valid_csrf_token(cookie_value) else None
        csrf_value = valid_cookie or secrets.token_urlsafe(32)
        set_cookie = bool(config.csrf_enabled and dashboard_surface and not valid_cookie)

        if config.csrf_enabled and dashboard_surface:
            csrf_context_token = _csrf_context.set(csrf_value)

        try:
            if config.rate_limit_enabled and path not in RATE_LIMIT_EXEMPT_PATHS:
                key = f"request:{client_address(scope)}"
                count, retry_after = _request_limiter.status(
                    key,
                    limit=config.request_limit,
                    window_seconds=config.request_window_seconds,
                    max_keys=config.max_rate_limit_keys,
                )
                if count >= config.request_limit:
                    try:
                        record_security_event(
                            "request.rate-limit",
                            "refused",
                            details={
                                "limit": config.request_limit,
                                "window_seconds": config.request_window_seconds,
                            },
                        )
                    except (SecurityAuditError, SecurityConfigError):
                        response = _security_json_response(
                            status_code=503,
                            detail="Security audit log is unavailable",
                            code="security-audit-unavailable",
                        )
                    else:
                        response = _security_json_response(
                            status_code=429,
                            detail="Request rate limit exceeded",
                            code="request-rate-limit-exceeded",
                            retry_after=max(1, math.ceil(retry_after)),
                        )
                    await response(scope, receive, send)
                    return

                _request_limiter.add(
                    key,
                    limit=config.request_limit,
                    window_seconds=config.request_window_seconds,
                    max_keys=config.max_rate_limit_keys,
                )

            effective_receive = receive
            if (
                config.csrf_enabled
                and dashboard_surface
                and method in BODY_METHODS
            ):
                body = await _read_body(receive)
                effective_receive = _replay_receive(body)
                submitted = _submitted_csrf_token(request, body)
                reason_code = "invalid-token"

                if not _same_origin(request):
                    reason_code = "cross-site"
                elif not valid_cookie:
                    reason_code = "missing-cookie"
                elif not submitted:
                    reason_code = "missing-token"
                elif not _valid_csrf_token(submitted):
                    reason_code = "invalid-token"
                elif secrets.compare_digest(submitted, valid_cookie):
                    reason_code = ""
                else:
                    reason_code = "token-mismatch"

                if reason_code:
                    try:
                        record_security_event(
                            "csrf.failure",
                            "refused",
                            details={"reason_code": reason_code},
                        )
                    except (SecurityAuditError, SecurityConfigError):
                        response = _security_json_response(
                            status_code=503,
                            detail="Security audit log is unavailable",
                            code="security-audit-unavailable",
                        )
                    else:
                        response = _security_json_response(
                            status_code=403,
                            detail="CSRF validation failed",
                            code="csrf-validation-failed",
                        )
                    if set_cookie:
                        response.raw_headers.append(
                            (
                                b"set-cookie",
                                _csrf_cookie_header(
                                    csrf_value,
                                    max_age=config.csrf_cookie_seconds,
                                ),
                            )
                        )
                    await response(scope, effective_receive, send)
                    return

            async def secured_send(message: dict[str, Any]) -> None:
                if set_cookie and message.get("type") == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append(
                        (
                            b"set-cookie",
                            _csrf_cookie_header(
                                csrf_value,
                                max_age=config.csrf_cookie_seconds,
                            ),
                        )
                    )
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, effective_receive, secured_send)
        finally:
            _request_context.reset(context_token)
            if csrf_context_token is not None:
                _csrf_context.reset(csrf_context_token)
