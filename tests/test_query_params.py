import asyncio

import httpx
from fastapi import Depends, FastAPI

from greentechhub_fastapi.query import PageParams


def _build_app():
    app = FastAPI()

    @app.get("/items")
    async def list_items(params: PageParams = Depends()):
        page_request = params.to_page_request()
        return {
            "page": page_request.page,
            "size": page_request.size,
            "sort": [{"field": s.field, "direction": s.direction} for s in page_request.sort],
            "filters": [
                {"field": f.field, "operator": str(f.operator), "value": f.value}
                for f in page_request.filters
            ],
        }

    return app


async def _get(app, params=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/items", params=params)


def test_defaults_match_fastapi_pagination_params_defaults():
    app = _build_app()
    response = asyncio.run(_get(app))
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["size"] == 50
    assert body["sort"] == []
    assert body["filters"] == []


def test_page_below_one_is_rejected_natively():
    app = _build_app()
    response = asyncio.run(_get(app, params={"page": 0}))
    assert response.status_code == 422


def test_size_above_max_is_rejected_natively():
    app = _build_app()
    response = asyncio.run(_get(app, params={"size": 1000}))
    assert response.status_code == 422


def test_sort_and_filter_parsed_end_to_end():
    app = _build_app()
    response = asyncio.run(
        _get(app, params={"sort": "-created_at,name", "filter": "status:eq:active"})
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sort"] == [
        {"field": "created_at", "direction": "desc"},
        {"field": "name", "direction": "asc"},
    ]
    assert body["filters"] == [{"field": "status", "operator": "eq", "value": "active"}]


def test_malformed_sort_returns_422_with_detail():
    app = _build_app()
    response = asyncio.run(_get(app, params={"sort": "-"}))
    assert response.status_code == 422
    assert "invalid sort clause" in response.json()["detail"]


def test_malformed_filter_returns_422_with_detail():
    app = _build_app()
    response = asyncio.run(_get(app, params={"filter": "status:matches:active"}))
    assert response.status_code == 422
