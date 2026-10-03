"""render — mapping greentechhub-core's ApplicationError hierarchy to HTTP status
codes and a JSON-serializable error body.

greentechhub-core's error classes only hint at HTTP "territory" in their
docstrings (e.g. NotFoundError is "404 territory") and take no position on the
exact status code — that mapping is this adapter's job to invent. ValidationError
is mapped to 422 rather than core's looser "400/422" hint specifically to match
FastAPI's own convention for request validation failures (its built-in
RequestValidationError handler already returns 422), so a service's own domain
validation errors and FastAPI's built-in ones look consistent to a client rather
than arbitrarily differing.

An error can also carry its own status: core's optional `status_code` hint
(core v0.9) wins over this type mapping when it's a valid HTTP status (100-599),
for errors whose status is only known at runtime, e.g. an upstream's 502 vs 503.
An out-of-range hint is ignored, so it can't produce an invalid response.
"""

from typing import Any

from greentechhub_core.types import (
    ApplicationError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)

STATUS_CODES: dict[type[ApplicationError], int] = {
    ApplicationError: 500,
    BadRequestError: 400,
    NotFoundError: 404,
    ValidationError: 422,
    ConflictError: 409,
    UnauthorizedError: 401,
    ForbiddenError: 403,
}


def status_code_for(exc: ApplicationError) -> int:
    """The HTTP status code for `exc`: its own `status_code` hint when that's a
    valid status, else the closest match walking its MRO.

    Not a plain `STATUS_CODES[type(exc)]` lookup: a future subclass of, say,
    NotFoundError that isn't itself added to STATUS_CODES should still resolve
    to 404 via its nearest mapped ancestor, not fall through to the 500
    default just because its exact type was never registered.
    """
    hint = getattr(exc, "status_code", None)
    if isinstance(hint, int) and not isinstance(hint, bool) and 100 <= hint <= 599:
        return hint
    for cls in type(exc).__mro__:
        if cls in STATUS_CODES:
            return STATUS_CODES[cls]
    return 500


def render_error_body(exc: ApplicationError) -> dict[str, Any]:
    """The JSON error envelope body: {"code", "message", "details"}."""
    return {"code": exc.code, "message": exc.message, "details": exc.details}
