from __future__ import annotations

from app.api import ui
from app.api.app import app
from app.version import APP_VERSION


def test_dashboard_routes_have_single_active_authority() -> None:
    root_get_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/" and "GET" in (getattr(route, "methods", None) or set())
    ]
    submit_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/submit-form"
        and "POST" in (getattr(route, "methods", None) or set())
    ]
    assert len(root_get_routes) == 1
    assert len(submit_routes) == 1


def test_active_dashboard_uses_authoritative_version() -> None:
    assert ui.APP_VERSION == APP_VERSION
    assert app.version == APP_VERSION
