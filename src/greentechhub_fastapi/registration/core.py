"""register_core — request-id, timing, security headers, CORS, and trusted-proxy
correction, wired onto a FastAPI app in one call.

Middleware add order below matters. Starlette's Starlette.add_middleware prepends
to its internal list, and build_middleware_stack wraps in reverse — net effect:
whichever middleware is added *last* ends up *outermost*, i.e. it's the first to
see an incoming request and the last to touch an outgoing response.
ProxyHeadersMiddleware is therefore added last here, deliberately: it must correct
scope["client"]/scope["scheme"]/the Host header *before* everything else below
runs, so RequestIDMiddleware's logging, CORSMiddleware's origin decisions, and any
route handler reading request.client all see the real client, not a trusted
proxy's own address.
"""

from fastapi import FastAPI
from greentechhub_core.config import GTHBaseSettings
from starlette.middleware.cors import CORSMiddleware

from greentechhub_fastapi.middleware import (
    ProxyHeadersMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    TimingMiddleware,
)
from greentechhub_fastapi.registration._settings import read_list_setting


def register_core(app: FastAPI, settings: GTHBaseSettings) -> None:
    """Wire request-id, timing, security-header, CORS, and trusted-proxy middleware.

    CORS_ALLOWED_ORIGINS and a trusted-proxies-equivalent field
    (TRUSTED_PROXIES) are read tolerantly via read_list_setting — neither is
    declared on GTHBaseSettings, so a service that hasn't declared them yet gets
    empty/restrictive defaults (no CORS origins allowed, no proxy headers
    trusted) rather than an AttributeError.
    """
    cors_origins = read_list_setting(settings, "CORS_ALLOWED_ORIGINS")
    trusted_proxies = read_list_setting(settings, "TRUSTED_PROXIES")

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added last so it ends up outermost — see module docstring.
    app.add_middleware(ProxyHeadersMiddleware, trusted_proxies=trusted_proxies)
