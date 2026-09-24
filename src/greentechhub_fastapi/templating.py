"""Template-side glue for a greentechhub-ui app on FastAPI/Starlette —
the FastAPI half of greentechhub-ui's framework-neutral setup helpers
(greentechhub_ui.install / static_dirs; see its docs/contract.md "Setup").
Nothing here imports greentechhub-ui: it takes plain mappings and requests,
so this package keeps no dependency on it.

    templates = Jinja2Templates(directory="templates", context_processors=[ui_context])
    greentechhub_ui.install(templates.env, service_name="…", nav_items=[…])
    mount_static_dirs(app, greentechhub_ui.static_dirs())
"""

from collections.abc import Mapping
from os import PathLike
from typing import Any

from starlette.requests import Request
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp


def ui_context(request: Request) -> dict[str, Any]:
    """A Jinja2Templates context processor supplying the per-request part of
    greentechhub-ui's template contract that isn't a global: current_path —
    what gth_sidebar / gth_navbar mark active and nav_breadcrumbs resolves.
    (gth-django's context processor supplies the same key.) Note Starlette
    applies context processors after the route's own context, so this value
    wins over a route's current_path."""
    return {"current_path": request.url.path}


def mount_static_dirs(app: ASGIApp, dirs: Mapping[str, str | PathLike[str]]) -> None:
    """Mount each `prefix -> directory` as static files, e.g.
    mount_static_dirs(app, greentechhub_ui.static_dirs()). The mount name is
    the prefix without slashes ("/gth-assets" → "gth-assets"), usable with
    request.url_for(name, path=…)."""
    for prefix, directory in dirs.items():
        name = prefix.strip("/").replace("/", "-")
        app.mount(prefix, StaticFiles(directory=directory), name=name)
