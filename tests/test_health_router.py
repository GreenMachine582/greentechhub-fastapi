import asyncio

import httpx
from greentechhub_core.health import HealthResult

from tests.conftest import build_app


def _ok(detail="fine"):
    async def _check():
        return HealthResult(status="healthy", detail=detail, latency_ms=1.0)

    return _check


def _unhealthy(detail="broken"):
    async def _check():
        return HealthResult(status="unhealthy", detail=detail, latency_ms=1.0)

    return _check


def _boom(message="connection refused"):
    async def _check():
        raise RuntimeError(message)

    return _check


async def _get(app, path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_liveness_always_200_healthy(settings):
    app = build_app(settings, checks=[_unhealthy()])
    response = asyncio.run(_get(app, "/health"))
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_readiness_200_when_all_checks_healthy(settings):
    app = build_app(settings, checks=[_ok(), _ok()])
    response = asyncio.run(_get(app, "/health/ready"))
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_readiness_503_when_a_check_is_unhealthy(settings):
    app = build_app(settings, checks=[_ok(), _unhealthy()])
    response = asyncio.run(_get(app, "/health/ready"))
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


def test_readiness_body_contains_individual_check_results(settings):
    app = build_app(settings, checks=[_ok(detail="db ok"), _unhealthy(detail="cache down")])
    response = asyncio.run(_get(app, "/health/ready"))
    details = [c["detail"] for c in response.json()["checks"]]
    assert details == ["db ok", "cache down"]


def test_readiness_survives_a_raising_check(settings):
    app = build_app(settings, checks=[_boom("db down")])
    response = asyncio.run(_get(app, "/health/ready"))
    assert response.status_code == 503
    assert "db down" in response.json()["checks"][0]["detail"]
