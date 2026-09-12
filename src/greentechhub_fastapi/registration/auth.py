"""register_auth — wires the configured auth adapter's implementation onto
Depends(get_current_user) via app.dependency_overrides (see auth/dependency.py
for why that mechanism, not app.state, is what makes adapter-swapping a config
change rather than a code change).

AUTH_ADAPTER is read tolerantly (not declared on GTHBaseSettings, same as
CORS_ALLOWED_ORIGINS/TRUSTED_PROXIES), defaulting to "local" — safe/working
out of the box, matching this package's established posture.

secret_key for DevelopmentIdentityProvider is settings.secret_key:
greentechhub-core's own identity/provider.py docstring explicitly declines to
mandate this relationship, leaving it to the adapter to decide — reusing the
one secret every service already has via GTHBaseSettings is the pragmatic,
single-secret choice, made explicit here rather than left implicit.

"forward_auth" is a real, documented AUTH_ADAPTER value (docs/auth.md), now
implemented as of v0.5: AuthentikIdentityProvider() is built with its
defaults (already matching Authentik's documented, stable forward-auth
header shape — no settings hook for overriding them exists or is needed
yet) and wired the same way "local" is. Its actual security gate is not
here — it's ProxyHeadersMiddleware's request.state.trusted_proxy flag (see
middleware/proxy_headers.py and auth/forward_auth.py); register_auth never
touches TRUSTED_PROXIES itself. Any other adapter value is a plain
misconfiguration and raises ValueError.
"""

from fastapi import FastAPI
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.identity import AuthentikIdentityProvider, DevelopmentIdentityProvider

from greentechhub_fastapi.auth.dependency import get_current_user
from greentechhub_fastapi.auth.forward_auth import build_forward_auth_get_current_user
from greentechhub_fastapi.auth.local import build_local_get_current_user
from greentechhub_fastapi.registration._settings import read_str_setting

_KNOWN_ADAPTERS = ("local", "forward_auth")


def register_auth(app: FastAPI, settings: GTHBaseSettings) -> None:
    adapter = read_str_setting(settings, "AUTH_ADAPTER", "local")

    if adapter == "local":
        provider = DevelopmentIdentityProvider(secret_key=settings.secret_key)
        app.dependency_overrides[get_current_user] = build_local_get_current_user(provider)
        return

    if adapter == "forward_auth":
        provider = AuthentikIdentityProvider()
        app.dependency_overrides[get_current_user] = build_forward_auth_get_current_user(provider)
        return

    raise ValueError(f"Unknown AUTH_ADAPTER={adapter!r}; expected one of {_KNOWN_ADAPTERS!r}.")
