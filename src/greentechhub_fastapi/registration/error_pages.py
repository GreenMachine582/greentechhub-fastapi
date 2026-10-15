"""register_error_pages — greentechhub-ui's 403.html / 404.html / 500.html for
browser page requests, leaving API and htmx requests to the JSON defaults.

Opt-in like every register_* call; call it after register_exception_handlers
and register_api_error_handlers. FastAPI keeps one handler per exception
class, so each handler here wraps the one already registered (or FastAPI's
default) and hands it every request that isn't a page request:

  - an HTTPException or core ApplicationError with status 403 or 404 renders
    403.html / 404.html through `templates` (context processors included, so
    the shell has its user menu and nav), with home_url, login_url and the
    error's own message when it has one;
  - any other exception renders 500.html, failure-proof: straight from the
    Jinja environment with a minimal context (error_reference from the
    request id, current_path, home_url, csp_nonce), since a context
    processor may need the very database that just failed. If even that
    fails, it's a plain-text 500. Starlette still logs and re-raises it.

A page request accepts text/html, isn't htmx (an htmx swap of a whole page
into a fragment target is never wanted) and isn't under `api_prefix`.
"""

import inspect
import logging
from collections.abc import Callable
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from greentechhub_core.logging import get_request_id
from greentechhub_core.types import ApplicationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from greentechhub_fastapi.exceptions.pages import wants_error_page
from greentechhub_fastapi.exceptions.render import render_error_body, status_code_for

logger = logging.getLogger(__name__)

PAGES = {403: "403.html", 404: "404.html"}
SERVER_ERROR_PAGE = "500.html"


def register_error_pages(
    app: FastAPI,
    settings: Any = None,
    *,
    templates: Jinja2Templates,
    api_prefix: str = "/api",
    home_url: str = "/",
    login_url: str = "/login",
) -> None:
    """Install the error pages. `settings` is accepted for symmetry with the
    other register_* calls."""
    if app.middleware_stack is not None:
        raise RuntimeError("register_error_pages must run before the app starts")
    previous_http = app.exception_handlers.get(StarletteHTTPException, http_exception_handler)
    previous_app_error = app.exception_handlers.get(ApplicationError)
    previous_server = app.exception_handlers.get(Exception)

    def page(request: Request, status: int, message: str | None) -> Response:
        context: dict[str, Any] = {"home_url": home_url, "login_url": login_url}
        if message:
            context["error_message"] = message
        return templates.TemplateResponse(request, PAGES[status], context, status_code=status)

    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code in PAGES and wants_error_page(request, api_prefix):
            generic = str(exc.detail) == HTTPStatus(exc.status_code).phrase
            return page(request, exc.status_code, None if generic else str(exc.detail))
        return await _call(previous_http, request, exc)

    async def application_error(request: Request, exc: ApplicationError) -> Response:
        status = status_code_for(exc)
        if status in PAGES and wants_error_page(request, api_prefix):
            return page(request, status, str(exc) or None)
        if previous_app_error is not None:
            return await _call(previous_app_error, request, exc)
        return JSONResponse(status_code=status, content=render_error_body(exc))

    async def server_error(request: Request, exc: Exception) -> Response:
        if not wants_error_page(request, api_prefix):
            if previous_server is not None:
                return await _call(previous_server, request, exc)
            return PlainTextResponse("Internal Server Error", status_code=500)
        return _server_error_page(templates, request, home_url)

    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(ApplicationError, application_error)
    app.add_exception_handler(Exception, server_error)


def _server_error_page(templates: Jinja2Templates, request: Request, home_url: str) -> Response:
    try:
        state = request.state
        context = {
            "error_reference": get_request_id() or request.headers.get("x-request-id"),
            "current_path": request.url.path,
            "home_url": home_url,
            "current_user": None,
            "csp_nonce": getattr(state, "csp_nonce", None),
        }
        html = templates.env.get_template(SERVER_ERROR_PAGE).render(context)
    except Exception:  # the page must never be the second failure
        logger.exception("rendering %s failed", SERVER_ERROR_PAGE)
        return PlainTextResponse("Internal Server Error", status_code=500)
    return HTMLResponse(html, status_code=500)


async def _call(handler: Callable[..., Any], request: Request, exc: Exception) -> Response:
    response = handler(request, exc)
    if inspect.isawaitable(response):
        response = await response
    return response
