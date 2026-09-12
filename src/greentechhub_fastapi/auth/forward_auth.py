"""build_forward_auth_get_current_user — the Authentik-backed forward-auth
adapter's concrete Depends(get_current_user) implementation.

A factory, not a bare function, same reasoning as local.py's
build_local_get_current_user: a real implementation needs a configured
AuthentikIdentityProvider closed over it.

Trust gate: reads request.state.trusted_proxy — set once, per request, by
ProxyHeadersMiddleware.__call__ from the *original*, pre-rewrite remote_addr
(see middleware/proxy_headers.py) — rather than recomputing
is_trusted_proxy(request.client.host, ...) here. Recomputing against
request.client.host would be checking the *already-resolved end-user IP*
ProxyHeadersMiddleware rewrites scope["client"] to once a request is
confirmed to have come through a trusted proxy — that IP is essentially
never itself in the trusted-proxy allowlist, so a naive re-check here would
reject every legitimate forwarded request. See docs/auth.md.

getattr(request.state, "trusted_proxy", False), never a bare attribute
read: a service that selects AUTH_ADAPTER=forward_auth without ever calling
register_core (so ProxyHeadersMiddleware never ran) must fail closed — no
state was ever set, and Starlette's State.__getattr__ raises AttributeError
on a missing key — not surface a 500 that could let an attacker distinguish
"misconfigured deployment" from "not logged in".

No is_trusted_proxy/settings.trusted_proxies re-read here at all: reusing
the exact boolean ProxyHeadersMiddleware already computed (rather than
re-reading TRUSTED_PROXIES independently) is what guarantees register_core
and register_auth can never disagree about which proxies are trusted —
there is only one trust decision, made once, at the one place that ever
sees the real remote_addr.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request
from greentechhub_core.identity import AuthentikIdentityProvider, Identity, RawAuthContext


def build_forward_auth_get_current_user(
    provider: AuthentikIdentityProvider,
) -> Callable[[Request], Awaitable[Identity | None]]:
    async def _get_current_user(request: Request) -> Identity | None:
        if not getattr(request.state, "trusted_proxy", False):
            return None
        return await provider.resolve(RawAuthContext(headers=request.headers))

    return _get_current_user
