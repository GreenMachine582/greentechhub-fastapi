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
an explicit fastapi.HTTPException(422, ...), which does produce a clean,
documented error response. Do not "simplify" this back into a validator.
"""

from fastapi import HTTPException, Query
from fastapi_pagination import Params
from greentechhub_core.query.types import PageRequest

from greentechhub_fastapi.query.parsing import parse_filters, parse_sort


class PageParams(Params):
    sort: str | None = Query(
        None, description='Comma-separated sort fields, e.g. "-created_at,name".'
    )
    filter: str | None = Query(
        None, description='Comma-separated "field:operator:value" clauses.'
    )

    def to_page_request(self) -> PageRequest:
        """Translate this request's page/size/sort/filter into a PageRequest.

        A malformed sort/filter string raises HTTPException(422) with the
        underlying ValueError's message as `detail` — page/size are already
        validated natively by the inherited Params fields' ge/le constraints,
        so no equivalent handling is needed for them here.
        """
        try:
            sort = parse_sort(self.sort)
            filters = parse_filters(self.filter)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return PageRequest(page=self.page, size=self.size, sort=sort, filters=filters)
