import asyncio

import httpx

from tests.conftest import build_app


async def _get(app, path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_security_headers_present_on_every_response(settings):
    app = build_app(settings)
    response = asyncio.run(_get(app, "/health"))
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
