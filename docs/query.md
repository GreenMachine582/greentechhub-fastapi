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
