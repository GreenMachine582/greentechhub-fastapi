[← Back to README](../README.md)

# 🔐 Auth Adapter

The concrete FastAPI implementation of `greentechhub-core`'s `IdentityProvider` (see that package's identity model doc).

```python
# greentechhub_fastapi/auth/local.py
def build_local_get_current_user(provider, *, cookie_name=SESSION_COOKIE_NAME):
    async def get_current_user(request: Request) -> Identity | None:
        token = request.cookies.get(cookie_name)
        if not token:
            return None
        return await provider.resolve(RawAuthContext(token=token))
    return get_current_user

# greentechhub_fastapi/auth/forward_auth.py
def build_forward_auth_get_current_user(provider):
    async def get_current_user(request: Request) -> Identity | None:
        # Security-critical gate — do not skip: request.state.trusted_proxy is
        # set once, per request, by ProxyHeadersMiddleware from the request's
        # *original* remote_addr. Never re-derive this from request.client.host,
        # which ProxyHeadersMiddleware may already have rewritten to the
        # resolved end-user IP once a request is confirmed forwarded — checking
        # that IP against the trusted-proxy allowlist would reject every
        # legitimate request.
        if not getattr(request.state, "trusted_proxy", False):
            return None
        return await provider.resolve(RawAuthContext(headers=request.headers))
    return get_current_user
```

`register_auth(app, settings)` (see [docs/registration.md](registration.md)) builds one of these two factories based on `settings.AUTH_ADAPTER` (`local` | `forward_auth`) and registers the result as the `get_current_user` dependency every route uses. Swapping from local dev auth to Authentik forward-auth is a **config change** (`AUTH_ADAPTER=forward_auth`), not a code change — this is the property the whole `IdentityProvider` design in `greentechhub-core` exists to guarantee. Only the `local` implementation is expected to be thrown away later; `forward_auth` is the durable path.

`forward_auth`'s trust decision is made in exactly one place: `ProxyHeadersMiddleware` (registered by `register_core`), from the connection's real remote address, before anything rewrites `request.client`. It exposes the result as `request.state.trusted_proxy`, and `forward_auth`'s `get_current_user` only ever reads that flag — it never calls `is_trusted_proxy` itself, so `register_core` and `register_auth` can't disagree about which proxies are trusted. **This means `register_core` must be called (with `TRUSTED_PROXIES` listing the Authentik outpost's real address) for `forward_auth` to ever resolve an identity** — a service that sets `AUTH_ADAPTER=forward_auth` but skips `register_core` gets a permanently-locked-out app (fails closed), not a security hole. Without this gate, any direct, untrusted connection could set `X-authentik-username` etc. itself and impersonate anyone. `AuthentikIdentityProvider` ships only the forward-auth header path today; OIDC token validation (`X-authentik-jwt` against the issuer's JWKS) needs a live Authentik instance and is planned for `greentechhub-core` v0.5.1.

Login/logout routes (`POST /auth/login`, `POST /auth/logout`) are thin — they call a service's own credential-check logic (e.g. a service's existing login endpoint) and then use this module purely to set/clear the session cookie.
