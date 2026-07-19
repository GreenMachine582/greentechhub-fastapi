"""register_exception_handlers — catches greentechhub-core's ApplicationError
hierarchy and translates it into the shared JSON error envelope.

JSON-only: docs/exceptions.md also mentions an HTML error page for "web
routes", but that's a deliberate scope narrowing for this task, not an
oversight — no templating dependency (Jinja2 etc.) exists anywhere in this
codebase yet, and none of the conventions for what a "web route" even is have
been established (that's flash/templates territory, a later v0.4-equivalent
milestone). Revisit once those land.

A single handler registered for the base ApplicationError is sufficient for
every subclass: Starlette's exception-handler dispatch walks the raised
exception's MRO and would prefer a more specific registered handler if one
existed (verified against the installed starlette version), so a consuming
service remains free to register its own handler for one particular subclass
(e.g. a custom NotFoundError response) after calling this function, without
needing to touch this module.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from greentechhub_core.types import ApplicationError

from greentechhub_fastapi.exceptions.render import render_error_body, status_code_for


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def _handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(status_code=status_code_for(exc), content=render_error_body(exc))
