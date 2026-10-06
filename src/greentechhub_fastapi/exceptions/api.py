"""register_api_error_handlers — the {code, message, details} envelope for
everything under an API prefix, not just core's ApplicationErrors.

register_exception_handlers covers ApplicationError. A JSON API also meets
errors FastAPI and Starlette raise themselves (an unknown route, a 405,
OAuth2PasswordBearer's 401, request validation), which otherwise come back in
FastAPI's own `{"detail": ...}` shapes, so a client would see two formats.
Under the prefix these become the envelope too; everywhere else keeps
FastAPI's defaults, so web pages (HTML errors, login redirects, HX-Redirect)
are untouched. Opt-in: call it alongside register_exception_handlers.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from greentechhub_core.types import UnauthorizedError
from starlette.exceptions import HTTPException as StarletteHTTPException

from greentechhub_fastapi.exceptions.render import render_error_body, status_code_for

#: The envelope `code` for an HTTPException's status; other statuses get "http_<status>".
HTTP_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "too_many_requests",
}


def _envelope(status_code: int, code: str, message: str, details: Any = None,
              headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, headers=headers,
                        content={"code": code, "message": message, "details": details})


def register_api_error_handlers(
    app: FastAPI, prefix: str = "/api", *, www_authenticate: str | None = "Bearer"
) -> None:
    """Answer every error under `prefix` with the {code, message, details}
    envelope:

    - Starlette/FastAPI HTTPException (unknown routes, 405, OAuth2's 401, ones
      a route raises): the envelope at the same status, keeping its headers;
      `code` from HTTP_STATUS_CODES.
    - RequestValidationError: 422 `validation_error`, the errors as `details`.
    - core's UnauthorizedError: its envelope plus `WWW-Authenticate:
      <www_authenticate>` (the OAuth2 bearer challenge; None to omit).

    Outside the prefix FastAPI's defaults apply (UnauthorizedError keeps the
    envelope, without the header). Every other ApplicationError is
    register_exception_handlers' job — call both.
    """
    base = "/" + prefix.strip("/")

    def _is_api(request: Request) -> bool:
        path = request.url.path
        return path == base or path.startswith(base + "/")

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        if not _is_api(request):
            return await http_exception_handler(request, exc)
        code = HTTP_STATUS_CODES.get(exc.status_code, f"http_{exc.status_code}")
        headers = getattr(exc, "headers", None)
        return _envelope(exc.status_code, code, str(exc.detail), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        if not _is_api(request):
            return await request_validation_exception_handler(request, exc)
        return _envelope(422, "validation_error", "Invalid request", jsonable_encoder(exc.errors()))

    @app.exception_handler(UnauthorizedError)
    async def _unauthorized(request: Request, exc: UnauthorizedError) -> JSONResponse:
        challenge = www_authenticate and _is_api(request)
        headers = {"WWW-Authenticate": www_authenticate} if challenge else None
        return JSONResponse(status_code=status_code_for(exc), content=render_error_body(exc),
                            headers=headers)
