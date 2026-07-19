"""register_health — thin wrapper mounting health_router onto a service's app."""

from collections.abc import Sequence

from fastapi import FastAPI

from greentechhub_fastapi.health import Check, health_router


def register_health(app: FastAPI, *, checks: Sequence[Check] = ()) -> None:
    """Mount /health and /health/ready, running `checks` for readiness.

    `checks` matches health_router's own contract: zero-arg async callables
    returning HealthResult; wrap checks needing arguments yourself
    (`lambda: check_database(engine)`).
    """
    app.include_router(health_router(checks=checks))
