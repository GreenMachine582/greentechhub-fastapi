[← Back to README](../README.md)

# 🔌 Service Registration

Wiring middleware and dependencies by hand, service by service, doesn't scale. This package makes registration explicit and one-line-per-concern instead:

```python
from fastapi import FastAPI
from greentechhub_fastapi import register_core, register_logging, register_health, register_auth

app = FastAPI()
register_logging(app, settings)
register_core(app, settings)      # request-id, timing, security headers, CORS
register_health(app, checks=[check_database])
register_auth(app, settings)      # picks local vs. forward_auth from settings.auth_adapter
```

CORS is bundled into `register_core` rather than a separate call — it reads allowed origins from a `CORS_ALLOWED_ORIGINS`-style field on the service's `Settings`, defaulting to empty/restrictive so a service is safe out of the box and one env var away from configured.

Each `register_*` function is small and composable — a service can skip ones it doesn't need (a pure internal API might skip `register_auth`) rather than getting an all-or-nothing bundle.

A service's own `Settings` still extends `greentechhub-core`'s `GTHBaseSettings` directly:

```python
from greentechhub_core.config import GTHBaseSettings

class Settings(GTHBaseSettings):
    ASYNC_DATABASE_URL: str
```

`greentechhub-core` is still imported directly for pure contracts (`Settings`, `Page`, `ApplicationError`) — only the framework-touching pieces route through this package.

See [docs/auth.md](auth.md), [docs/health.md](health.md), and [docs/modules.md](modules.md) for what each `register_*` call actually wires up.
