"""PageParams.to_page_request(fields) and validated_filter_json: a client's
filters checked against allowed fields with greentechhub-core's
validate_filters, normalised, or a 400 invalid_filters envelope."""

import asyncio
import json
from datetime import date

import httpx
import pytest
from fastapi import Depends, FastAPI
from greentechhub_core.query import Filter, FilterField, FilterGroup, Operator
from greentechhub_core.types import BadRequestError

from greentechhub_fastapi import register_exception_handlers
from greentechhub_fastapi.query import PageParams, validated_filter_json

FIELDS = [
    FilterField(key="name", type="text"),
    FilterField(key="stock", type="number"),
    FilterField(key="added", type="date"),
    FilterField(key="category", type="choice", choices=["Sensor", "Cable"]),
]


def _plain(clause):
    if isinstance(clause, FilterGroup):
        return {clause.mode: [_plain(c) for c in clause.filters]}
    value = clause.value.isoformat() if isinstance(clause.value, date) else clause.value
    return {"field": clause.field, "op": str(clause.operator), "value": value,
            "type": type(clause.value).__name__}


def _app(fields=FIELDS, **limits):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/items")
    async def items(params: PageParams = Depends()):
        request = params.to_page_request(fields, **limits)
        return [_plain(f) for f in request.filters]

    return app


def _get(app, **params):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/items", params=params)

    return asyncio.run(go())


def test_without_fields_nothing_changes():
    response = _get(_app(fields=None), filter="anything:eq:5")
    assert response.json() == [{"field": "anything", "op": "eq", "value": "5", "type": "str"}]


def test_both_filter_forms_are_normalised():
    tree = [{"field": "added", "op": ">=", "value": "2026-01-31"},
            {"or": [{"field": "category", "op": "in", "value": ["Sensor"]},
                    {"field": "name", "op": "contains", "value": "bolt"}]}]
    response = _get(_app(), filter="stock:gt:10", filters=json.dumps(tree))
    assert response.status_code == 200
    assert response.json() == [
        {"field": "stock", "op": "gt", "value": 10, "type": "int"},
        {"field": "added", "op": "gte", "value": "2026-01-31", "type": "date"},
        {"or": [{"field": "category", "op": "in", "value": ["Sensor"], "type": "list"},
                {"field": "name", "op": "contains", "value": "bolt", "type": "str"}]},
    ]


def test_problems_are_a_400_with_a_detail_per_clause():
    tree = [{"field": "secret", "op": "eq", "value": 1},
            {"and": [{"field": "stock", "op": "contains", "value": "1"}]}]
    response = _get(_app(), filters=json.dumps(tree))
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_filters"
    assert [(d["path"], d["field"]) for d in body["details"]] == [("0", "secret"), ("1.0", "stock")]


def test_malformed_input_is_still_a_422():
    response = _get(_app(), filters="{not json")
    assert response.status_code == 422


def test_limits_pass_through():
    response = _get(_app(max_filters=1), filter="stock:gt:1,stock:lt:9")
    assert response.status_code == 400
    assert response.json()["details"][0]["message"] == "at most 1 filters"


def test_validated_filter_json_for_a_form_field():
    raw = json.dumps({"field": "stock", "op": "lte", "value": "4.5"})
    assert validated_filter_json(raw, FIELDS) == [
        Filter(field="stock", operator=Operator.LTE, value=4.5)]
    assert validated_filter_json("", FIELDS) == []
    with pytest.raises(BadRequestError) as malformed:
        validated_filter_json("[1, 2", FIELDS)
    assert malformed.value.code == "invalid_filters"
    assert malformed.value.details[0]["path"] is None
    with pytest.raises(BadRequestError) as invalid:
        validated_filter_json(json.dumps({"field": "category", "op": "eq", "value": "Motor"}),
                              {f.key: f for f in FIELDS})
    assert invalid.value.details == [{"path": "0", "field": "category",
                                      "message": "'category' 'Motor' isn't one of the choices"}]
