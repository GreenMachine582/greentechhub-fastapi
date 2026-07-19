"""render — turns greentechhub-core's HealthResult list into this package's own
/health/ready JSON shape.
"""

from dataclasses import asdict

from greentechhub_core.health import HealthResult, HealthStatus


def overall_status(results: list[HealthResult]) -> HealthStatus:
    """"unhealthy" if any result is unhealthy, else "healthy". An empty list of
    results (register_health called with no checks) is "healthy" — there's nothing
    to be unhealthy about, matching /health/ready's role as "ready if everything
    we were told to check is fine"."""
    return "unhealthy" if any(r.status == "unhealthy" for r in results) else "healthy"


def render_health_results(results: list[HealthResult]) -> dict:
    """Build the /health/ready response body from a list of HealthResult.

    Each HealthResult is rendered via dataclasses.asdict — safe even though
    HealthResult is frozen+slots, since asdict works off dataclasses.fields(),
    not __dict__.
    """
    return {
        "status": overall_status(results),
        "checks": [asdict(r) for r in results],
    }
