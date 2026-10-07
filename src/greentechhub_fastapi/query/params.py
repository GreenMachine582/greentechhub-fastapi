"""PageParams — the Depends()-compatible FastAPI dependency docs/query.md refers
to as where "fastapi-pagination and FastAPI's Query(...) parsing actually live".

Subclasses fastapi_pagination.Params (a pydantic BaseModel) rather than
reimplementing page/size parsing: fastapi_pagination.Params already declares
page: int = Query(1, ge=1) and size: int = Query(50, ge=1, le=100), and adding
new Query(...)-defaulted fields to a BaseModel subclass used via Depends()
works cleanly with FastAPI's dependency resolution and shows up correctly in
the OpenAPI schema (verified against the installed fastapi-pagination 0.15).

sort/filter parsing is deliberately NOT done via a pydantic field_validator:
verified that a validator raising ValueError on a Params subclass resolved
through Depends() does not become a clean 422 — it surfaces as an unhandled
pydantic_core.ValidationError, i.e. a bare 500. Instead, to_page_request()
below calls the plain parsing.py functions itself and turns a ValueError into
a QueryParamError (a 400 HTTPException with a code), which does produce a
clean, documented error response. Do not "simplify" this back into a
validator.
"""

from collections.abc import Iterable, Mapping

from fastapi import HTTPException, Query
from fastapi_pagination import Params
from greentechhub_core.query import FilterField, validate_filters
from greentechhub_core.query.types import PageRequest

from greentechhub_fastapi.query.parsing import parse_filter_json, parse_filters, parse_sort


class QueryParamError(HTTPException):
    """A malformed sort/filter/filters value: 400, the reason as `detail`,
    and a `code` ("invalid_sort" or "invalid_filters") that
    register_api_error_handlers puts in the envelope. A plain HTTPException,
    so an app without those handlers still answers a clean 400."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(status_code=400, detail=message)
        self.code = code


class PageParams(Params):
    sort: str | None = Query(
        None, description='Comma-separated sort fields, e.g. "-created_at,name".'
    )
    filter: str | None = Query(
        None, description='Comma-separated "field:operator:value" clauses.'
    )
    filters: str | None = Query(
        None,
        description='JSON filter clauses, AND-ed: {"field", "op", "value"} leaves and '
        '{"and": [...]} / {"or": [...]} groups.',
    )

    def to_page_request(
        self,
        fields: Iterable[FilterField] | Mapping[str, FilterField] | None = None,
        *,
        max_depth: int = 3,
        max_filters: int = 20,
        max_values: int = 100,
    ) -> PageRequest:
        """Translate this request's page/size/sort/filter into a PageRequest.

        `filter` (the flat string) and `filters` (JSON, with and/or groups)
        may both be given; their clauses are AND-ed together.

        A malformed sort raises QueryParamError("invalid_sort"), a malformed
        filter/filters QueryParamError("invalid_filters"): a 400 with the
        reason as `detail` (the API envelope's `message`). page/size are
        validated natively by the inherited Params fields' ge/le constraints
        (FastAPI's 422).

        With `fields` (core FilterFields), the clauses also go through core's
        validate_filters: only those fields, the operators each type takes,
        values that fit (converted to numbers, dates and bools), and the
        limits given. A problem raises core's BadRequestError
        ("invalid_filters", a {path, field, message} detail per clause), which
        the registered exception handlers answer 400.
        """
        try:
            sort = parse_sort(self.sort)
        except ValueError as exc:
            raise QueryParamError("invalid_sort", f"Invalid 'sort': {exc}") from exc
        try:
            filters = [*parse_filters(self.filter), *parse_filter_json(self.filters)]
        except ValueError as exc:
            raise QueryParamError("invalid_filters", f"Invalid 'filters': {exc}") from exc
        if fields is not None:
            filters = validate_filters(filters, fields, max_depth=max_depth,
                                       max_filters=max_filters, max_values=max_values)
        return PageRequest(page=self.page, size=self.size, sort=sort, filters=filters)
