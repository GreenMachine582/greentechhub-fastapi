"""parsing — turns this package's own query-string wire format for sorting and
filtering into greentechhub-core's Sort/Filter types.

Neither greentechhub-core's query/types.py nor docs/query.md's code sample define
a concrete wire format (the sample only shows page/size; README's Scope table
promises Filter/Sort support without specifying the syntax) — this module invents
one, deliberately minimal:

  sort=field1,-field2,...
    Comma-separated field names, in priority order. A leading "-" means
    descending; no prefix means ascending (Sort.direction's own default).

  filter=field:operator:value,field2:operator2:value2,...
    Comma-separated clauses, each "field:operator:value" split with maxsplit=2
    so a value may itself contain ":" (e.g. an ISO timestamp). operator must be
    one of Operator's raw string values (parsed via Operator(raw), which raises
    ValueError naturally for anything else, since Operator is a StrEnum).
      - IN / NOT_IN: value is "|"-separated (not "," — that already separates
        whole clauses) into a list[str], e.g. "status:in:active|pending".
      - IS_NULL: value must be "true"/"false" (case-insensitive) -> bool.
      - every other operator: value passed through as a plain str untouched —
        this module has no knowledge of the target field's real type (int,
        datetime, ...); that coercion belongs to whichever adapter eventually
        executes the Filter against a real data source, same rationale as
        Filter.value's own "Any" typing.

  filters=<JSON>  (parse_filter_json)
    For what the flat string can't say: AND/OR groups (core's FilterGroup,
    v0.9), and values with commas or real types. A JSON list of clauses
    (AND-ed) or one clause; a clause is a leaf {"field", "op", "value"} or a
    group {"and": [...]} / {"or": [...]}, nested up to MAX_FILTER_DEPTH. `op`
    is an Operator value or one of the symbol aliases ==, !=, >, >=, <, <=
    (the sqlalchemy-filters spec's). Values keep their JSON types, so numbers
    stay numbers; in/not_in need a list, is_null a bool. No NOT group: negate
    per clause (ne, not_in, is_null false), as core does.

All default to None/absent -> [], matching PageRequest's own field defaults.
The flat `filter` string stays flat; a value containing a literal "," is a
known limitation of it (use `filters`, or build Filter/Sort objects
programmatically).

Malformed input (bad clause shape, unknown operator, non-bool is_null value, an
empty in/not_in list) raises a plain ValueError — this file stays fastapi-free
so it's testable without an app; the fastapi-touching layer (params.py) is
responsible for turning that into an HTTP-visible error.

validated_filter_json adds greentechhub-core's validate_filters (allowed
fields, operators per type, values converted to their types) for a query
builder's JSON posted in a form; it raises core's BadRequestError
("invalid_filters") for any problem, malformed JSON included.
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from greentechhub_core.query import FilterField, validate_filters
from greentechhub_core.query.types import Filter, FilterGroup, Operator, Sort
from greentechhub_core.types import BadRequestError

_LIST_OPERATORS = {Operator.IN, Operator.NOT_IN}


def parse_sort(raw: str | None) -> list[Sort]:
    """Parse a "field1,-field2" sort string into an ordered list[Sort]."""
    if not raw:
        return []

    clauses = []
    for clause in raw.split(","):
        clause = clause.strip()
        if not clause or clause == "-":
            raise ValueError(f"invalid sort clause: {clause!r}")
        if clause.startswith("-"):
            clauses.append(Sort(field=clause[1:], direction="desc"))
        else:
            clauses.append(Sort(field=clause, direction="asc"))
    return clauses


def parse_filters(raw: str | None) -> list[Filter]:
    """Parse a "field:operator:value,..." filter string into a list[Filter]."""
    if not raw:
        return []

    filters = []
    for clause in raw.split(","):
        parts = clause.split(":", maxsplit=2)
        if len(parts) != 3:
            raise ValueError(f"invalid filter clause: {clause!r}")
        field, raw_operator, raw_value = (p.strip() for p in parts)
        if not field:
            raise ValueError(f"invalid filter clause: {clause!r}")
        operator = Operator(raw_operator)
        value = _parse_filter_value(operator, raw_value)
        filters.append(Filter(field=field, operator=operator, value=value))
    return filters


def _parse_filter_value(operator: Operator, raw_value: str) -> str | list[str] | bool:
    if operator in _LIST_OPERATORS:
        values = [v for v in raw_value.split("|") if v]
        if not values:
            raise ValueError(f"{operator} filter requires at least one value")
        return values
    if operator is Operator.IS_NULL:
        lowered = raw_value.lower()
        if lowered not in ("true", "false"):
            raise ValueError(f"is_null filter value must be true/false, got {raw_value!r}")
        return lowered == "true"
    return raw_value


#: How deep and/or groups may nest in parse_filter_json — enough for a query
#: builder's all/any with sub-groups, small enough to bound a hostile request.
MAX_FILTER_DEPTH = 5

_OPERATOR_ALIASES = {"==": "eq", "!=": "ne", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}


def parse_filter_json(raw: str | None) -> list[Filter | FilterGroup]:
    """Parse the JSON `filters` form into a list of Filter / FilterGroup
    (AND-ed, as PageRequest.filters is). See the module docstring."""
    if raw is None or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"filters is not valid JSON: {exc.msg}") from None
    clauses = data if isinstance(data, list) else [data]
    return [_parse_clause(c, depth=1) for c in clauses]


def validated_filter_json(
    raw: str | None,
    fields: Iterable[FilterField] | Mapping[str, FilterField],
    *,
    max_depth: int = 3,
    max_filters: int = 20,
    max_values: int = 100,
) -> list[Filter | FilterGroup]:
    """parse_filter_json, then greentechhub-core's validate_filters against
    `fields`: for a query builder's JSON posted in a form field. Anything
    wrong, malformed JSON included, raises one BadRequestError
    ("invalid_filters"); a parse problem is a single detail with path None."""
    try:
        filters = parse_filter_json(raw)
    except ValueError as exc:
        raise BadRequestError(str(exc), code="invalid_filters",
                              details=[{"path": None, "field": None, "message": str(exc)}]) from exc
    return validate_filters(filters, fields, max_depth=max_depth, max_filters=max_filters,
                            max_values=max_values)


def _parse_clause(node: Any, *, depth: int) -> Filter | FilterGroup:
    if not isinstance(node, dict):
        raise ValueError(f"a filter clause must be an object, got {node!r}")
    if "and" in node or "or" in node:
        if len(node) != 1:
            raise ValueError(f"a filter group has exactly one key, and/or: {node!r}")
        if depth >= MAX_FILTER_DEPTH:
            raise ValueError(f"filter groups nest at most {MAX_FILTER_DEPTH} deep")
        mode, items = next(iter(node.items()))
        if not isinstance(items, list):
            raise ValueError(f'"{mode}" takes a list of clauses')
        children = tuple(_parse_clause(i, depth=depth + 1) for i in items)
        return FilterGroup(mode=mode, filters=children)
    if "not" in node:
        raise ValueError('"not" groups are not supported: negate per clause (ne, not_in, is_null)')
    if set(node) != {"field", "op", "value"}:
        raise ValueError(f'a filter clause is {{"field", "op", "value"}}, got {sorted(node)}')
    field, raw_op, value = node["field"], node["op"], node["value"]
    if not isinstance(field, str) or not field:
        raise ValueError(f"invalid filter field: {field!r}")
    if not isinstance(raw_op, str):
        raise ValueError(f"invalid filter op: {raw_op!r}")
    operator = Operator(_OPERATOR_ALIASES.get(raw_op, raw_op))
    if operator in _LIST_OPERATORS and not isinstance(value, list):
        raise ValueError(f"{operator} takes a list, got {value!r}")
    if operator is Operator.IS_NULL and not isinstance(value, bool):
        raise ValueError(f"is_null takes true/false, got {value!r}")
    return Filter(field=field, operator=operator, value=value)
