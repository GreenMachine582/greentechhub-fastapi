"""PageParams.to_page_request answers malformed sort/filter input with a
400 QueryParamError: invalid_sort / invalid_filters in the API envelope, and
a clean 400 with `detail` in an app without the error handlers."""

import asyncio

import httpx
from fastapi import Depends, FastAPI

from greentechhub_fastapi.exceptions import register_api_error_handlers, register_exception_handlers
from greentechhub_fastapi.query import PageParams, QueryParamError


def _app(*, handlers: bool) -> FastAPI:
    app = FastAPI()
    if handlers:
        register_exception_handlers(app)
        register_api_error_handlers(app, prefix="/api")

    @app.get("/api/items")
    async def items(params: PageParams = Depends()):
        request = params.to_page_request()
        return {"sort": len(request.sort), "filters": len(request.filters)}

    return app


def _get(app, **params):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/items", params=params)

    return asyncio.run(run())


def test_a_bad_sort_is_invalid_sort_in_the_envelope():
    resp = _get(_app(handlers=True), sort="-")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "invalid_sort" and body["message"].startswith("Invalid 'sort': ")


def test_a_bad_filter_or_filters_is_invalid_filters():
    for params in ({"filter": "status:matches:active"}, {"filters": "{not json"}):
        resp = _get(_app(handlers=True), **params)
        assert resp.status_code == 400
        assert resp.json()["code"] == "invalid_filters"
        assert resp.json()["message"].startswith("Invalid 'filters': ")


def test_without_the_handlers_it_is_still_a_clean_400():
    resp = _get(_app(handlers=False), sort="-")
    assert resp.status_code == 400
    assert resp.json()["detail"].startswith("Invalid 'sort': ")


def test_good_input_still_parses():
    resp = _get(_app(handlers=True), sort="-a,b", filter="x:eq:1")
    assert resp.json() == {"sort": 2, "filters": 1}


def test_query_param_error_is_an_http_exception_with_a_code():
    exc = QueryParamError("invalid_sort", "Invalid 'sort': bad")
    assert (exc.status_code, exc.code, exc.detail) == (400, "invalid_sort", "Invalid 'sort': bad")
