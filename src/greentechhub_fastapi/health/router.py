"""health_router — the /health (liveness) and /health/ready (readiness) routes every
GreenTechHub-ecosystem FastAPI service exposes.

Split from render.py: this file is FastAPI-touching (imports fastapi), render.py is
not (it only imports greentechhub_core), keeping the JSON-shape decision testable
without spinning up an app.

Shape/status-code choices (this package's own, since neither greentechhub-core nor
greentechhub-django define one yet):
  - GET /health        — pure liveness. No checks run. Always 200 {"status": "healthy"}
    if the app process is up enough to answer at all. Never fails on its own; a
    monitoring/orchestration layer using this as a liveness probe should restart the
    process only when even *this* stops responding.
  - GET /health/ready   — readiness. Runs `checks` via greentechhub_core.health.run_checks
    concurrently, 200 if every result is healthy, 503 otherwise. Body is
    render.render_health_results(results) either way, so a caller always gets the
    detail even on failure — matching HealthResult's own "detail" field intent.
"""

from collections.abc import Awaitable, Callable, Sequence

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from greentechhub_core.health import HealthResult, run_checks

from greentechhub_fastapi.health.render import render_health_results

Check = Callable[[], Awaitable[HealthResult]]


def health_router(*, checks: Sequence[Check] = ()) -> APIRouter:
    """Build an APIRouter exposing /health and /health/ready.

    `checks` are zero-arg async callables returning HealthResult, run concurrently
    by greentechhub_core.health.run_checks — a service wraps checks needing
    arguments itself, e.g. `lambda: check_database(engine)` (matching run_checks'
    own documented convention). Defaults to an empty sequence so a service with no
    dependencies yet can still call register_health(app, checks=[]) — or skip
    registration entirely — without this function requiring an argument.
    """
    router = APIRouter()

    @router.get("/health")
    async def liveness() -> dict:
        return {"status": "healthy"}

    @router.get("/health/ready")
    async def readiness() -> JSONResponse:
        results = await run_checks(checks)
        body = render_health_results(results)
        status_code = 200 if body["status"] == "healthy" else 503
        return JSONResponse(content=body, status_code=status_code)

    return router
