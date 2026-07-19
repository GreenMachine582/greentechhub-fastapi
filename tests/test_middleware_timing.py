import asyncio

import httpx

from tests.conftest import build_app


async def _get(app, path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_x_response_time_header_present_and_parses_as_a_number(settings):
    app = build_app(settings)
    response = asyncio.run(_get(app, "/health"))
    header = response.headers["X-Response-Time"]
    assert header.endswith("ms")
    assert float(header[: -len("ms")]) >= 0
