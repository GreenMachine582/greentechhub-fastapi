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

Both default to None/absent -> [], matching PageRequest's own field defaults.
OR-groups/nesting are explicitly out of scope: PageRequest.filters is a flat,
implicitly-AND-ed list per its own docstring, so there's no richer shape to
parse into. A filter/sort value containing a literal "," is a known, documented
limitation of this minimal format, not something this module tries to escape —
a service needing that should build Filter/Sort objects programmatically instead
of via the query string.

Malformed input (bad clause shape, unknown operator, non-bool is_null value, an
empty in/not_in list) raises a plain ValueError — this file stays fastapi-free
so it's testable without an app; the fastapi-touching layer (params.py) is
responsible for turning that into an HTTP-visible error.
"""

from greentechhub_core.query.types import Filter, Operator, Sort

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
