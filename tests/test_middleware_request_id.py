import asyncio

import httpx
from fastapi import FastAPI
from greentechhub_core.logging import get_request_id

from greentechhub_fastapi.registration.core import register_core


def _build_app(settings):
    app = FastAPI()
    register_core(app, settings)

    @app.get("/probe")
    async def probe():
        return {"request_id": get_request_id()}

    return app


async def _get(app, path, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def test_request_id_header_present_on_response(settings):
    app = _build_app(settings)
    response = asyncio.run(_get(app, "/probe"))
    assert response.headers["X-Request-ID"]


def test_incoming_request_id_header_is_echoed_back_unchanged(settings):
    app = _build_app(settings)
    response = asyncio.run(_get(app, "/probe", headers={"X-Request-ID": "fixed-id"}))
    assert response.headers["X-Request-ID"] == "fixed-id"
    assert response.json()["request_id"] == "fixed-id"


def test_request_id_context_var_set_during_handling_and_reset_after(settings):
    app = _build_app(settings)
    assert get_request_id() is None
    response = asyncio.run(_get(app, "/probe"))
    assert response.json()["request_id"] is not None
    assert get_request_id() is None


def test_two_requests_get_different_request_ids(settings):
    app = _build_app(settings)
    first = asyncio.run(_get(app, "/probe"))
    second = asyncio.run(_get(app, "/probe"))
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
