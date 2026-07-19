import asyncio
import logging

import httpx
from fastapi import FastAPI

from greentechhub_fastapi import register_core, register_health, register_logging
from tests.conftest import build_app


async def _get(app, path, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def test_register_logging_is_idempotent_across_repeated_registration(settings, capsys):
    app = FastAPI()
    register_logging(app, settings)
    register_logging(app, settings)
    logging.getLogger("gth.test.registration").info("only once")

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1


def test_full_reference_app_responds_on_all_registered_surfaces(settings):
    app = build_app(settings)
    response = asyncio.run(_get(app, "/health"))

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Response-Time"].endswith("ms")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_cors_allowed_origins_empty_by_default_blocks_cross_origin(settings):
    app = build_app(settings)
    response = asyncio.run(
        _get(app, "/health", headers={"Origin": "https://not-allowed.example"})
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_allowed_origins_configured_allows_listed_origin(settings):
    settings.CORS_ALLOWED_ORIGINS = "https://allowed.example"
    app = FastAPI()
    register_core(app, settings)
    register_health(app)

    response = asyncio.run(
        _get(app, "/health", headers={"Origin": "https://allowed.example"})
    )
    assert response.headers["access-control-allow-origin"] == "https://allowed.example"
