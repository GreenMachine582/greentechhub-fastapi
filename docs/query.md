[← Back to README](../README.md)

# 🔍 Query Adapter

```python
from greentechhub_fastapi.query import PageParams
from greentechhub_core.query.types import Page

@router.get("/transactions")
async def list_transactions(params: PageParams = Depends()) -> Page[TransactionRead]:
    page_request = params.to_page_request()   # -> greentechhub_core PageRequest
    ...
    return Page(items=..., total=..., page=params.page, size=params.size)
```

`PageParams` is where `fastapi-pagination` and FastAPI's `Query(...)` parsing actually live — a service never imports `fastapi-pagination` directly, it's an implementation detail of this module, not a public dependency. If `fastapi-pagination` were ever replaced, only this module changes.

## Server-rendered "load more" paging

HTML pages that page with HTMX (`gth_pagination` / `gth_table_load_more` in `greentechhub-ui`) need two more pieces, both in `greentechhub_fastapi.query`:

```python
from greentechhub_fastapi.query import PageParams, next_page_url, page_params

@router.get("/stocks/rows")
async def stock_rows(request: Request, q: str = "",
                     params: PageParams = Depends(page_params(default_size=50))):
    page = ...  # a greentechhub_core Page for this page/size
    return templates.TemplateResponse(request, "_rows.html", {
        "stocks": page.items,
        "next_url": next_page_url("/stocks/rows", page, {"q": q}),
    })
```

- `page_params(default_size=50, max_size=100)` — a `Depends()`-ready builder that parses only `page`/`size`, with a per-endpoint default size read at call time. Pages take their own named filter params rather than `PageParams`' generic `sort`/`filter` strings.
- `next_page_url(path, page, filters)` — the next page's URL with the current filters carried over (empty ones dropped), or `None` on the last page.

## Filter groups (`filters=`, JSON)

`PageParams` reads two filter params, and their clauses are AND-ed together:

- `filter=status:eq:active,stock:gt:0` — the flat string form: field, operator and value, AND-ed. Values are text.
- `filters=<JSON>` — for what the string can't say: AND/OR groups (greentechhub-core v0.9's `FilterGroup`), and
  values with commas or real types. It's a list of clauses (AND-ed) or one clause. A clause is a leaf
  `{"field", "op", "value"}` or a group `{"and": [...]}` / `{"or": [...]}`, and groups nest:

```text
?filters=[{"field":"category","op":"in","value":["Sensor","Cable"]},
          {"or":[{"field":"stock","op":"eq","value":0},{"field":"name","op":"contains","value":"bolt"}]}]
```

- `op` is a core `Operator` (`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`, `starts_with`,
  `ends_with`, `is_null`), or one of the symbol aliases `==`, `!=`, `>`, `>=`, `<`, `<=` used by the
  `sqlalchemy-filters` spec.
- Values keep their JSON types, so `5` stays a number. `in` / `not_in` take a list; `is_null` takes `true`/`false`.
- There's no `not` group: negate per clause (`ne`, `not_in`, `is_null: false`), as core does. Groups nest at most
  `MAX_FILTER_DEPTH` (5) deep. Anything malformed is a 422 with the reason in `detail`.

The result goes straight into greentechhub-core's SQLAlchemy helpers, with the field allow-list applied there:

```python
from greentechhub_core.query import to_envelope
from greentechhub_core.sqlalchemy import page

@router.get("/stocks")
async def list_stocks(params: PageParams = Depends(), session=Depends(get_session)):
    result = await page(session, select(Stock), params.to_page_request(), ALLOWED,
                        default_sort=[Sort(field="id")])
    return to_envelope(result)
```

`parse_filter_json(raw)` is exported from `greentechhub_fastapi.query` for routes that read the JSON elsewhere,
such as a form field.
