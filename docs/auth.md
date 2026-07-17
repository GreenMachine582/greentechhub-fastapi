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
    return await AuthentikIdentityProvider().resolve(
        RawAuthContext(headers=request.headers)
    )
```

`register_auth(app, settings)` (see [docs/registration.md](registration.md)) picks one of these based on `settings.auth_adapter` (`local` | `forward_auth`) and registers it as the `get_current_user` dependency every route uses. Swapping from local dev auth to Authentik forward-auth is a **config change** (`AUTH_ADAPTER=forward_auth`), not a code change — this is the property the whole `IdentityProvider` design in `greentechhub-core` exists to guarantee. Only the `local` implementation is expected to be thrown away later; `forward_auth` is the durable path.

Login/logout routes (`POST /auth/login`, `POST /auth/logout`) are thin — they call a service's own credential-check logic (e.g. a service's existing login endpoint) and then use this module purely to set/clear the session cookie.
