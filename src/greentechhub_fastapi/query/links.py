"""page_params / next_page_url — the two pieces of "load more" paging glue
every server-rendered consumer was hand-writing (BottleBot's watchlist,
PyFinBot's stocks/transactions tables).

- page_params(default_size=...) — a Depends()-ready PageParams builder with
  a per-page default size. PageParams' own Query defaults (size=50) are
  evaluated once at import time; a closure reading `default_size` at call
  time also lets tests monkeypatch a consumer's page-size constant.
  It only parses page/size: server-rendered pages take their own named
  filter params (q, status, ...), not PageParams' generic sort/filter
  strings.
- next_page_url(path, page, filters) — the URL of the page after `page`,
  carrying the current filters, or None on the last page. Neither Page nor
  PageParams has any notion of a next link, and gth_pagination /
  gth_table_load_more (greentechhub-ui) render exactly this.
"""

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

from fastapi import Query
from greentechhub_core.query.types import Page

from greentechhub_fastapi.query.params import PageParams


def page_params(default_size: int = 50, max_size: int = 100) -> Callable[..., PageParams]:
    def dependency(
        page: int = Query(1, ge=1),
        size: int | None = Query(None, ge=1, le=max_size),
    ) -> PageParams:
        return PageParams(page=page, size=size if size is not None else default_size)

    return dependency


def next_page_url(path: str, page: Page, filters: Mapping[str, Any] | None = None) -> str | None:
    """None when `page` is the last one; otherwise `path?<filters>&page=N+1&size=S`.
    Filters with a None or "" value are dropped so URLs stay short and a
    cleared filter doesn't round-trip as `q=`."""
    if page.page * page.size >= page.total:
        return None
    params = {k: v for k, v in (filters or {}).items() if v not in (None, "")}
    params.update(page=page.page + 1, size=page.size)
    return f"{path}?{urlencode(params)}"
