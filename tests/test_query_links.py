import asyncio

import httpx
from fastapi import Depends, FastAPI
from greentechhub_core.query.types import Page

from greentechhub_fastapi.query import PageParams, next_page_url, page_params


def _build_app(**kwargs):
    app = FastAPI()

    @app.get("/items")
    async def list_items(params: PageParams = Depends(page_params(**kwargs))):
        return {"page": params.page, "size": params.size}

    return app


async def _get(app, params=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/items", params=params)


def test_page_params_uses_the_given_default_size():
    response = asyncio.run(_get(_build_app(default_size=20)))
    assert response.json() == {"page": 1, "size": 20}


def test_page_params_explicit_size_wins():
    response = asyncio.run(_get(_build_app(default_size=20), params={"page": 3, "size": 5}))
    assert response.json() == {"page": 3, "size": 5}


def test_page_params_bounds_are_validated():
    app = _build_app(max_size=10)
    assert asyncio.run(_get(app, params={"size": 11})).status_code == 422
    assert asyncio.run(_get(app, params={"page": 0})).status_code == 422


def _page(page, size, total):
    return Page(items=[], total=total, page=page, size=size)


def test_next_page_url_is_none_on_the_last_page():
    assert next_page_url("/rows", _page(2, 10, 20)) is None
    assert next_page_url("/rows", _page(1, 10, 0)) is None


def test_next_page_url_carries_filters_and_drops_empty_ones():
    url = next_page_url("/rows", _page(1, 10, 25), {"q": "bhp", "market": "", "status": None})
    assert url == "/rows?q=bhp&page=2&size=10"


def test_next_page_url_encodes_values():
    url = next_page_url("/rows", _page(1, 10, 25), {"sort": "-date,id", "q": "a&b"})
    assert url == "/rows?sort=-date%2Cid&q=a%26b&page=2&size=10"
