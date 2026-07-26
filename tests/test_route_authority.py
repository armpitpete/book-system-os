from __future__ import annotations

import inspect

from app.api import app as app_module
from app.api import ui
from app.api.app import app
from app.version import APP_VERSION


def matching_routes(path: str, method: str) -> list:
    return [
        route
        for route in app.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
    ]


def test_dashboard_routes_have_single_active_authority() -> None:
    root_get_routes = matching_routes("/", "GET")
    submit_routes = matching_routes("/submit-form", "POST")

    assert len(root_get_routes) == 1
    assert len(submit_routes) == 1
    assert root_get_routes[0].endpoint is ui.dashboard
    assert submit_routes[0].endpoint is ui.submit_form
    assert root_get_routes[0].endpoint.__module__ == "app.api.ui"
    assert submit_routes[0].endpoint.__module__ == "app.api.ui"


def test_application_does_not_patch_or_delete_dashboard_routes() -> None:
    source = inspect.getsource(app_module)

    assert "ui.router.routes" not in source
    assert "ui.page =" not in source
    assert "inject_csrf_fields" not in source
    assert "submission_router" not in source


def test_dashboard_renders_post_forms_through_one_helper() -> None:
    source = inspect.getsource(ui)

    assert "def post_form(" in source
    assert "current_csrf_token()" in source
    assert "inject_csrf_fields" not in source


def test_active_dashboard_uses_authoritative_version() -> None:
    assert ui.APP_VERSION == APP_VERSION
    assert app.version == APP_VERSION
