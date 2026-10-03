import json

import pytest
from greentechhub_core.query.types import Filter, FilterGroup, Operator, Sort

from greentechhub_fastapi.query.parsing import (
    MAX_FILTER_DEPTH,
    parse_filter_json,
    parse_filters,
    parse_sort,
)


def test_parse_sort_none_returns_empty_list():
    assert parse_sort(None) == []


def test_parse_sort_empty_string_returns_empty_list():
    assert parse_sort("") == []


def test_parse_sort_single_ascending_field():
    assert parse_sort("name") == [Sort(field="name", direction="asc")]


def test_parse_sort_single_descending_field():
    assert parse_sort("-created_at") == [Sort(field="created_at", direction="desc")]


def test_parse_sort_multiple_mixed_fields():
    assert parse_sort("-created_at,name") == [
        Sort(field="created_at", direction="desc"),
        Sort(field="name", direction="asc"),
    ]


@pytest.mark.parametrize("raw", [",name", "-", "name,-"])
def test_parse_sort_malformed_raises(raw):
    with pytest.raises(ValueError):
        parse_sort(raw)


def test_parse_filters_none_returns_empty_list():
    assert parse_filters(None) == []


def test_parse_filters_empty_string_returns_empty_list():
    assert parse_filters("") == []


def test_parse_filters_eq_operator_passes_value_through_as_string():
    assert parse_filters("status:eq:active") == [
        Filter(field="status", operator="eq", value="active")
    ]


def test_parse_filters_value_containing_colon_survives_maxsplit():
    assert parse_filters("created_at:gte:2026-01-01T00:00:00Z") == [
        Filter(field="created_at", operator="gte", value="2026-01-01T00:00:00Z")
    ]


def test_parse_filters_multiple_clauses():
    assert parse_filters("status:eq:active,age:gte:18") == [
        Filter(field="status", operator="eq", value="active"),
        Filter(field="age", operator="gte", value="18"),
    ]


def test_parse_filters_in_operator_splits_pipe_separated_values():
    assert parse_filters("status:in:active|pending") == [
        Filter(field="status", operator="in", value=["active", "pending"])
    ]


def test_parse_filters_not_in_operator_splits_pipe_separated_values():
    assert parse_filters("status:not_in:archived") == [
        Filter(field="status", operator="not_in", value=["archived"])
    ]


def test_parse_filters_in_operator_empty_value_raises():
    with pytest.raises(ValueError):
        parse_filters("status:in:")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("deleted_at:is_null:true", True),
        ("deleted_at:is_null:TRUE", True),
        ("deleted_at:is_null:false", False),
        ("deleted_at:is_null:False", False),
    ],
)
def test_parse_filters_is_null_operator_parses_bool_case_insensitively(raw, expected):
    assert parse_filters(raw) == [Filter(field="deleted_at", operator="is_null", value=expected)]


def test_parse_filters_is_null_operator_invalid_value_raises():
    with pytest.raises(ValueError):
        parse_filters("deleted_at:is_null:yes")


def test_parse_filters_unknown_operator_raises():
    with pytest.raises(ValueError):
        parse_filters("status:matches:active")


@pytest.mark.parametrize("raw", ["status", "status:eq", ":eq:active", " :eq:active"])
def test_parse_filters_malformed_clause_shape_raises(raw):
    with pytest.raises(ValueError):
        parse_filters(raw)


# parse_filter_json — the JSON `filters` form, with and/or groups


def _leaf(field, op, value):
    return {"field": field, "op": op, "value": value}


@pytest.mark.parametrize("raw", [None, "", "  ", "[]"])
def test_filter_json_empty_is_no_filters(raw):
    assert parse_filter_json(raw) == []


def test_filter_json_single_clause_or_list():
    one = parse_filter_json(json.dumps(_leaf("stock", "gte", 5)))
    # The number stays a number.
    assert one == [Filter(field="stock", operator=Operator.GTE, value=5)]
    both = [_leaf("stock", "gte", 5), _leaf("name", "contains", "a,b")]
    many = parse_filter_json(json.dumps(both))
    assert [f.field for f in many] == ["stock", "name"] and many[1].value == "a,b"


def test_filter_json_nested_groups():
    raw = json.dumps([
        _leaf("category", "in", ["Sensor", "Cable"]),
        {"or": [_leaf("stock", "eq", 0), {"and": [_leaf("name", "starts_with", "x"),
                                                  _leaf("note", "is_null", False)]}]},
    ])
    parsed = parse_filter_json(raw)
    assert parsed[0] == Filter(field="category", operator=Operator.IN, value=["Sensor", "Cable"])
    group = parsed[1]
    assert isinstance(group, FilterGroup) and group.mode == "or"
    inner = group.filters[1]
    assert inner.mode == "and"
    assert inner.filters[1] == Filter(field="note", operator=Operator.IS_NULL, value=False)


@pytest.mark.parametrize(
    ("alias", "operator"),
    [("==", Operator.EQ), ("!=", Operator.NE), (">", Operator.GT), (">=", Operator.GTE),
     ("<", Operator.LT), ("<=", Operator.LTE)],
)
def test_filter_json_symbol_aliases(alias, operator):
    assert parse_filter_json(json.dumps(_leaf("stock", alias, 1)))[0].operator is operator


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{not json", "not valid JSON"),
        ('"stock"', "must be an object"),
        (json.dumps(_leaf("stock", "matches", 1)), "matches"),
        (json.dumps({"field": "stock", "op": "eq"}), '"field", "op", "value"'),
        (json.dumps({**_leaf("stock", "eq", 1), "extra": 1}), '"field", "op", "value"'),
        (json.dumps({"field": "", "op": "eq", "value": 1}), "invalid filter field"),
        (json.dumps({"not": _leaf("stock", "eq", 1)}), "not supported"),
        (json.dumps({"and": [], "or": []}), "exactly one key"),
        (json.dumps({"or": _leaf("stock", "eq", 1)}), "takes a list"),
        (json.dumps(_leaf("stock", "in", 1)), "takes a list"),
        (json.dumps(_leaf("note", "is_null", "true")), "true/false"),
    ],
)
def test_filter_json_rejects_malformed_input(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_filter_json(raw)


def test_filter_json_nesting_is_bounded():
    node = _leaf("stock", "eq", 1)
    for _ in range(MAX_FILTER_DEPTH - 1):
        node = {"and": [node]}
    assert parse_filter_json(json.dumps(node))  # at the limit: fine
    with pytest.raises(ValueError, match="nest at most"):
        parse_filter_json(json.dumps({"and": [node]}))
