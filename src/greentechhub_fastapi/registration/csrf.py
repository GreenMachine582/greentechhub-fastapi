"""register_csrf — CSRF tokens on every request, for the htmx forms of a
signed-in app (v0.16).

Opt-in like every register_* call. It installs CsrfMiddleware, which gives
each request a token (the gth_csrf double-submit cookie, set when new) that
ui_context passes to templates as `csrf_token`; greentechhub-ui's app shell
sends it on every htmx request and in the navbar's logout form. Nothing is
checked until a route depends on require_csrf, or a view opts in:
SettingsViews(csrf=True), RoleAdminViews(csrf=True), LoginViews.logout_csrf.
"""

from typing import Any

from fastapi import FastAPI

from greentechhub_fastapi.auth.csrf import CsrfMiddleware


def register_csrf(app: FastAPI, settings: Any = None) -> None:
    """Install CsrfMiddleware. `settings` is accepted for symmetry with the
    other register_* calls."""
    if app.middleware_stack is not None:
        raise RuntimeError("register_csrf must run before the app starts")
    app.add_middleware(CsrfMiddleware)
