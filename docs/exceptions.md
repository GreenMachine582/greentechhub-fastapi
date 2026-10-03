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
