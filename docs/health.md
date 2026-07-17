[← Back to README](../README.md)

# 🩺 Health Router

```python
from greentechhub_fastapi.health import health_router
from greentechhub_core.health.checks import check_database

app.include_router(health_router(checks=[
    lambda: check_database(engine),
]))
```

A router exposing `/health`/`/health/ready`, running `greentechhub-core`'s health checks against this service's actual dependencies (DB engine, etc.). Produces the same `HealthResult`-based JSON shape a Django service produces via `greentechhub-django`'s health view — monitoring tooling treats every service's `/health` identically regardless of which framework served it.
