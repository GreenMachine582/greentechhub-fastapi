"""build_local_get_current_user — the local/dev auth adapter's concrete
Depends(get_current_user) implementation.

A factory, not a bare function, because a real implementation needs a
configured DevelopmentIdentityProvider closed over it — the provider itself
needs secret_key (see registration/auth.py for where that comes from), and a
plain module-level function has no way to receive it other than through a
closure built at registration time.

This fixes two bugs in docs/auth.md's illustrative code sample, verified
against greentechhub_core.identity's actual source:
  - RawAuthContext has no `cookie` field; the real field is `token` (a bare
    token string, no "Bearer " prefix).
  - DevelopmentIdentityProvider() cannot be constructed with no arguments —
    secret_key is a required keyword-only constructor argument.

dev_mode is deliberately never set here (always the RawAuthContext default of
False) — wiring it to a new setting (e.g. a DEV_AUTH_BYPASS toggle) would be a
security-sensitive decision no doc asks for; this is a narrow, documented v0.3
scope choice, not an oversight.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity, RawAuthContext

from greentechhub_fastapi.auth.cookies import SESSION_COOKIE_NAME


def build_local_get_current_user(
    provider: DevelopmentIdentityProvider, *, cookie_name: str = SESSION_COOKIE_NAME
) -> Callable[[Request], Awaitable[Identity | None]]:
    async def _get_current_user(request: Request) -> Identity | None:
        token = request.cookies.get(cookie_name)
        if not token:
            return None
        return await provider.resolve(RawAuthContext(token=token))

    return _get_current_user
