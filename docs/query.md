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
