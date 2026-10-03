[← Back to README](../README.md)

# ⚠️ Exception Handling

```python
from greentechhub_fastapi.exceptions import register_exception_handlers
from greentechhub_core.types import ApplicationError

register_exception_handlers(app)   # ApplicationError -> {code, message, details} JSON, or HTML for web routes
```

`ApplicationError` and its subclasses live in `greentechhub-core` (pure Python exceptions with `code`/`message`/`details`); this module only handles the FastAPI-specific part — catching them and producing a `Response`, as either a JSON error envelope (API routes) or an HTML error page (web routes).

## Status codes

| Error | Status |
|---|---|
| `BadRequestError` | 400 |
| `UnauthorizedError` | 401 |
| `ForbiddenError` | 403 |
| `NotFoundError` | 404 |
| `ConflictError` | 409 |
| `ValidationError` | 422 (FastAPI's own convention for validation failures) |
| `ApplicationError` and anything else | 500 |

A subclass resolves through its nearest mapped ancestor. An error can also carry its own status, using core's
optional `status_code` hint (core v0.9) for statuses only known at runtime. It wins over the table when it's a valid
HTTP status (100–599); an out-of-range hint is ignored, so it can't produce an invalid response:

```python
raise ApplicationError("Mailbox unreachable", code="email_sync_failed", status_code=503)
# -> 503 {"code": "email_sync_failed", "message": "Mailbox unreachable", "details": null}
```

## JSON envelopes for an API prefix

`register_exception_handlers` covers core's `ApplicationError`s. A JSON API also meets errors FastAPI and Starlette
raise themselves, which otherwise come back in FastAPI's own `{"detail": ...}` shapes. `register_api_error_handlers`
makes everything under a prefix use the same `{code, message, details}` envelope, and leaves every other path on
FastAPI's defaults, so web pages (HTML errors, login redirects, HX-Redirect) don't change. It's opt-in; call both:

```python
from greentechhub_fastapi import register_api_error_handlers, register_exception_handlers

register_exception_handlers(app)
register_api_error_handlers(app, prefix="/api")   # www_authenticate="Bearer" by default
```

| Under the prefix | Response |
|---|---|
| An unknown route, a wrong method, or any `HTTPException` (including `OAuth2PasswordBearer`'s 401) | the envelope at its status, keeping its headers; `code` is `bad_request` / `unauthorized` / `forbidden` / `not_found` / `method_not_allowed` / `conflict` / `validation_error`, else `http_<status>` |
| A request validation error | 422 `validation_error`, "Invalid request", the error list as `details` |
| core's `UnauthorizedError` | the 401 envelope plus `WWW-Authenticate: Bearer` (the OAuth2 bearer challenge); `www_authenticate=None` omits it, and off the prefix it never has it |

The prefix matches whole path segments (`/api` doesn't catch `/apix`). Every other `ApplicationError` is
`register_exception_handlers`' job, including a per-error `status_code`.
