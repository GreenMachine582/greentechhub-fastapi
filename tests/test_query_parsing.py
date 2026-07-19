import pytest
from greentechhub_core.query.types import Filter, Sort

from greentechhub_fastapi.query.parsing import parse_filters, parse_sort


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
