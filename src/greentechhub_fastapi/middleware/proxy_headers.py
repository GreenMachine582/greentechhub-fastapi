"""ProxyHeadersMiddleware — corrects an ASGI request's perceived client IP, scheme,
and Host as seen by everything downstream (other middleware, route handlers,
request.client / request.url) when this service sits behind a trusted reverse
proxy, using greentechhub_core.proxy.resolve_forwarded's trust logic.

Must run outermost among this package's middleware (see registration/core.py's
comment on add_middleware ordering) — every other piece of request handling
(RequestIDMiddleware's logging, CORSMiddleware's origin checks, security headers,
route handlers reading request.client) should see the *corrected* values, not the
raw TCP peer address of a trusted proxy sitting in front of the real client.

trusted_proxies is resolved once, at registration time, from settings — not
re-read per request — matching resolve_forwarded's own "explicit allowlist, empty
by default" trust posture: an empty list trusts nothing, so a service that never
configures this middleware's trusted_proxies behaves exactly as if it weren't
installed.

Second responsibility: stamps scope["state"]["trusted_proxy"] with whether the
request's *original* remote_addr (before any rewrite below) was itself a trusted
proxy. This is computed once, here, because scope["client"] is about to be
overwritten with the resolved end-user IP when remote_addr is trusted — anything
downstream that re-checked is_trusted_proxy(request.client.host, ...) after that
rewrite would be checking the end-user's IP against the allowlist instead of the
proxy's, which is almost never true. auth/forward_auth.py's get_current_user
reads this flag instead of recomputing it.
"""

from collections.abc import Sequence

from greentechhub_core.proxy import is_trusted_proxy, resolve_forwarded
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send


class ProxyHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, trusted_proxies: Sequence[str] = ()) -> None:
        self.app = app
        self.trusted_proxies = trusted_proxies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        remote_addr = client[0] if client else ""
        trusted = is_trusted_proxy(remote_addr, self.trusted_proxies)

        scope = dict(scope)
        scope["state"] = {**scope.get("state", {}), "trusted_proxy": trusted}

        if not self.trusted_proxies:
            # No trusted_proxies configured: skip resolve_forwarded's work entirely
            # rather than calling it just to have it echo remote_addr back unchanged.
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        info = resolve_forwarded(
            remote_addr=remote_addr,
            headers=headers,
            trusted_proxies=self.trusted_proxies,
            default_scheme=scope.get("scheme", "http"),
            default_host=headers.get("host"),
        )

        scope["client"] = (info.client_ip, client[1] if client else 0)
        scope["scheme"] = info.scheme
        if info.host is not None:
            raw_headers = [(k, v) for k, v in scope["headers"] if k != b"host"]
            raw_headers.append((b"host", info.host.encode("latin-1")))
            scope["headers"] = raw_headers

        await self.app(scope, receive, send)
