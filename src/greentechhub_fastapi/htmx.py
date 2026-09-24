"""htmx response glue: the bodyless 204 whose only job is its HX-Trigger
header — what BottleBot's routes, PyFinBot's web/htmx.py and
greentechhub-ui's playground each hand-built.

The header value itself is built elsewhere and passed in, so this module
doesn't depend on greentechhub-ui: typically greentechhub_ui.toast(...)
(a toast, optionally with extra events) or greentechhub_ui.htmx.trigger(...)
(bare events). A Mapping is JSON-encoded as-is.
"""

import json
from collections.abc import Mapping
from typing import Any

from starlette.responses import Response


def hx_response(
    trigger: str | Mapping[str, Any],
    *,
    status_code: int = 204,
    content: str = "",
    headers: Mapping[str, str] | None = None,
) -> Response:
    """A response carrying `HX-Trigger`: e.g.
    `return hx_response(greentechhub_ui.toast("Saved", events=["closeModal"]))`.
    204 (no body, nothing swapped) by default; pass status_code=200 plus
    `content` to swap something in as well."""
    value = trigger if isinstance(trigger, str) else json.dumps(dict(trigger))
    return Response(
        content=content,
        status_code=status_code,
        headers={**(headers or {}), "HX-Trigger": value},
        media_type="text/html" if content else None,
    )
