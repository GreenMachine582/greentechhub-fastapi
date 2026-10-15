"""register_admin — mount a service's admin pages and get their "Admin" nav
group (greentechhub_fastapi.admin)."""

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from starlette.routing import Match

from greentechhub_fastapi.admin import AdminView, admin_nav_item


def register_admin(
    app: FastAPI,
    settings: Any = None,
    *,
    views: Iterable[AdminView],
    label: str = "Admin",
    icon: str = "gear",
) -> dict[str, Any]:
    """Mount each view's router and return admin_nav_item(views), the group
    to put in greentechhub-ui's nav items.

    A view whose url the app already routes (an AuditViews given to
    register_audit(views=)) isn't mounted again. `settings` is accepted for
    symmetry with the other register_* calls.
    """
    if app.middleware_stack is not None:
        raise RuntimeError("register_admin must run before the app starts")
    views = list(views)
    for view in views:
        if not _routed(app, view.url):
            app.include_router(view.router())
    return admin_nav_item(views, label=label, icon=icon)


def _routed(app: FastAPI, path: str) -> bool:
    """Whether a GET to `path` already reaches a route, through Starlette's
    public BaseRoute.matches (which also sees into included routers)."""
    scope = {"type": "http", "path": path, "method": "GET", "root_path": "", "headers": [],
             "query_string": b""}
    return any(route.matches(scope)[0] == Match.FULL for route in app.router.routes)
