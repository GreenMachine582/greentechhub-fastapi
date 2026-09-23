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

Login/logout routes (`POST /auth/login`, `POST /auth/logout`) are thin — they call a service's own credential-check logic (e.g. a service's existing login endpoint) and then use this module purely to set/clear the session cookie. Two ways to build them:

**Hand-write them** — the pattern above, useful when a service's login flow doesn't fit the common shape below (e.g. it's the bearer-token API login, not a browser session).

**Subclass `LoginViews`** (`greentechhub_fastapi.auth.LoginViews`) for the common browser-login case — a form-based `GET`/`POST /login` and `POST /logout`, with only the credential check left to fill in:

```python
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_fastapi.auth import LoginViews, resolve_dependency

class MyLoginViews(LoginViews):
    async def authenticate(self, user_id: str, password: str) -> Identity | None:
        async with resolve_dependency(app, get_session) as session:
            # your own DB lookup + password check; return None for bad credentials
            ...

router = MyLoginViews(
    templates=my_jinja2_templates,
    identity_provider=DevelopmentIdentityProvider(secret_key=settings.secret_key),
).router()
app.include_router(router)
```

`LoginViews` owns rendering `login_template` (a template name resolved against the `Jinja2Templates` instance you pass in — the service supplies the actual file), minting the session JWT via the `identity_provider` you construct and pass in, and setting/clearing the cookie. Note it's the caller's job to build that provider — same precedent as `register_auth(app, settings)` reading `AUTH_ADAPTER` and choosing/constructing the right one itself, rather than a shared class hardcoding `DevelopmentIdentityProvider` internally. It deliberately never touches a database or session itself either — `authenticate()` is a plain async method, not a route parameter, so it never goes through `Depends()`. That's what `resolve_dependency(app, dependency)` (`greentechhub_fastapi.auth.resolve_dependency`) is for: it calls an async-generator-shaped dependency (e.g. a service's own `get_session`) the way FastAPI would, honoring whatever's in `app.dependency_overrides` — so a subclass's `authenticate()` still gets a test DB substituted in tests, the same as any `Depends(get_session)` route already does — without a subclass having to hand-roll that lookup itself. `login_template`/`redirect_url`/`login_url` are overridable class attributes for services whose routes/branding don't match the defaults.

## Requiring a login on page routes

`get_current_user` resolves to `None` for anonymous callers, and `dependencies.get_current_identity` turns that into a 401 JSON envelope — right for APIs, wrong for browser pages. For server-rendered routes use `dependencies.require_page_identity(login_url="/login")`:

```python
from greentechhub_fastapi.dependencies import require_page_identity

page_identity = require_page_identity()          # login_url defaults to LoginViews.login_url
router = APIRouter(prefix="/stocks", dependencies=[Depends(page_identity)])

@router.get("/transactions")
async def transactions(identity: Identity = Depends(page_identity)): ...
```

- Normal request, not logged in → `303` to `login_url`.
- HTMX request (`HX-Request` header), not logged in → `401` with `HX-Redirect: login_url`. A 303 would be followed silently by the XHR and the login page swapped into whatever fragment was targeted; `HX-Redirect` makes HTMX navigate the whole page instead.
