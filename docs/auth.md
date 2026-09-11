[← Back to README](../README.md)

# 🔐 Auth Adapter

The concrete FastAPI implementation of `greentechhub-core`'s `IdentityProvider` (see that package's identity model doc).

```python
# greentechhub_fastapi/auth/local.py
async def get_current_user(request: Request) -> Identity | None:
    token = request.cookies.get("gth_session")
    if not token:
        return None
    return await DevelopmentIdentityProvider().resolve(RawAuthContext(cookie=token))

# greentechhub_fastapi/auth/forward_auth.py
async def get_current_user(request: Request) -> Identity | None:
    # Security-critical gate — do not skip: X-authentik-* headers are only
    # trustworthy once the connection is confirmed to have come through the
    # trusted proxy running the Authentik outpost. AuthentikIdentityProvider
    # deliberately never sees remote_addr and cannot do this check itself —
    # see greentechhub-core's docs/identity.md.
    if not is_trusted_proxy(request.client.host, settings.trusted_proxies):
        return None
    return await AuthentikIdentityProvider().resolve(
        RawAuthContext(headers=request.headers)
    )
```

`register_auth(app, settings)` (see [docs/registration.md](registration.md)) picks one of these based on `settings.auth_adapter` (`local` | `forward_auth`) and registers it as the `get_current_user` dependency every route uses. Swapping from local dev auth to Authentik forward-auth is a **config change** (`AUTH_ADAPTER=forward_auth`), not a code change — this is the property the whole `IdentityProvider` design in `greentechhub-core` exists to guarantee. Only the `local` implementation is expected to be thrown away later; `forward_auth` is the durable path.

`forward_auth`'s trusted-proxy gate (`proxy.trusted_proxy.is_trusted_proxy`, using `settings.trusted_proxies`) is not optional — without it, any direct, untrusted connection could set `X-authentik-username` etc. itself and impersonate anyone. `AuthentikIdentityProvider` ships only the forward-auth header path today; OIDC token validation (`X-authentik-jwt` against the issuer's JWKS) needs a live Authentik instance and is planned for `greentechhub-core` v0.5.1.

Login/logout routes (`POST /auth/login`, `POST /auth/logout`) are thin — they call a service's own credential-check logic (e.g. a service's existing login endpoint) and then use this module purely to set/clear the session cookie.
