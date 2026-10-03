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


# The JSON `filters` param: and/or groups alongside the flat `filter` string


def _shape(clause):
    if hasattr(clause, "mode"):
        return {clause.mode: [_shape(c) for c in clause.filters]}
    return [clause.field, str(clause.operator), clause.value]


def _groups_app():
    app = FastAPI()

    @app.get("/items")
    async def list_items(params: PageParams = Depends()):
        return [_shape(c) for c in params.to_page_request().filters]

    return app


def test_json_filters_and_the_flat_filter_combine():
    filters = '[{"or": [{"field": "stock", "op": "eq", "value": 0}, ' \
              '{"field": "name", "op": "contains", "value": "bolt"}]}]'
    response = asyncio.run(_get(_groups_app(), params={"filter": "status:eq:active",
                                                       "filters": filters}))
    assert response.status_code == 200
    assert response.json() == [
        ["status", "eq", "active"],
        {"or": [["stock", "eq", 0], ["name", "contains", "bolt"]]},
    ]


def test_malformed_json_filters_return_422_with_detail():
    response = asyncio.run(_get(_groups_app(), params={"filters": '{"not": {}}'}))
    assert response.status_code == 422
    assert "not supported" in response.json()["detail"]
