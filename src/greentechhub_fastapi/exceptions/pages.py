"""wants_error_page — which requests get an HTML error page (register_error_pages)
rather than the JSON defaults."""

from fastapi import Request


def wants_error_page(request: Request, api_prefix: str = "/api") -> bool:
    """Whether `request` is a browser page request, which gets an error page
    rather than JSON: it accepts text/html, isn't htmx and isn't under
    `api_prefix`."""
    base = "/" + api_prefix.strip("/")
    path = request.url.path
    under_api = base != "/" and (path == base or path.startswith(base + "/"))
    return ("text/html" in request.headers.get("accept", "")
            and "hx-request" not in request.headers and not under_api)
