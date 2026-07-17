[← Back to README](../README.md)

# ⚠️ Exception Handling

```python
from greentechhub_fastapi.exceptions import register_exception_handlers
from greentechhub_core.types import ApplicationError

register_exception_handlers(app)   # ApplicationError -> {code, message, details} JSON, or HTML for web routes
```

`ApplicationError` and its subclasses live in `greentechhub-core` (pure Python exceptions with `code`/`message`/`details`); this module only handles the FastAPI-specific part — catching them and producing a `Response`, as either a JSON error envelope (API routes) or an HTML error page (web routes).
