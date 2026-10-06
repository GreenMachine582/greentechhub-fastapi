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

`LoginViews` owns rendering `login_template` (a template name resolved against the `Jinja2Templates` instance you pass in), minting the session JWT via the `identity_provider` you construct and pass in, and setting/clearing the cookie. Note it's the caller's job to build that provider — same precedent as `register_auth(app, settings)` reading `AUTH_ADAPTER` and choosing/constructing the right one itself, rather than a shared class hardcoding `DevelopmentIdentityProvider` internally. It deliberately never touches a database or session itself either — `authenticate()` is a plain async method, not a route parameter, so it never goes through `Depends()`. That's what `resolve_dependency(app, dependency)` (`greentechhub_fastapi.auth.resolve_dependency`) is for: it calls an async-generator-shaped dependency (e.g. a service's own `get_session`) the way FastAPI would, honoring whatever's in `app.dependency_overrides` — so a subclass's `authenticate()` still gets a test DB substituted in tests, the same as any `Depends(get_session)` route already does — without a subclass having to hand-roll that lookup itself. `login_template`/`redirect_url`/`login_url` are overridable class attributes for services whose routes/branding don't match the defaults. When the service registers greentechhub-core's `landing_page_setting` through `register_settings`, a successful login lands on the user's chosen page instead, and `redirect_url` is the fallback (see [docs/registration.md](registration.md#settings)).

**The login page.** `login_template` defaults to `"login_page.html"`, greentechhub-ui's ready-made sign-in screen
(ui v0.14+): no app navbar, the brand above a card, the theme toggle and a footer. Mount greentechhub-ui's templates
(`greentechhub_ui.install(templates.env, ...)`) and there's nothing to write. `LoginViews` passes `login_url` (the
form's action) on every render, plus `error` and the submitted `user_id` after a failed login, so the user ID stays
filled in and focus moves to the password. The password is never sent back. The page's other options
(`login_title`, `login_subtitle`, `login_help`, `login_links`) can be set by overriding the template or the views'
render methods. Before v0.11 the default was `"login.html"`; to keep a page of your own:

```python
class MyLoginViews(LoginViews):
    login_template = "login.html"
```

Set `register_url` (e.g. `"/register"`) when the service offers sign-up: `LoginViews` then also passes `register_url`
to the template, so the sign-in page can link to "Create account". Left at `None`, nothing changes. The link is
also left out while core's self-signup setting (below) is off.
Set `forgot_password_url` (e.g. `"/forgot-password"`, see `PasswordResetViews` below) and the template gets it too,
for a "Forgot password?" link.

**Login throttling.** Pass core's `LoginThrottle` as `throttle=` to lock out repeated failed logins
([core docs](https://github.com/GreenMachine582/greentechhub-core/blob/main/docs/modules.md#login-throttling)):

```python
from greentechhub_core.security import LoginThrottle
from greentechhub_core.sqlalchemy import SQLAlchemyAttemptStore, login_attempts_table

attempts = SQLAlchemyAttemptStore(login_attempts_table(metadata), async_session_factory=async_session)
router = MyLoginViews(templates=..., identity_provider=..., throttle=LoginThrottle(attempts)).router()
```

- Failures count against the account (the user ID, ignoring case and spaces) **and** the client address, so neither
  one guesser trying many accounts nor many clients trying one account gets unlimited tries. By default 5 failures
  within 15 minutes lock a key for 15 minutes.
- A locked-out attempt, including the failure that trips the lock, re-renders the sign-in page with status 429, a
  `Retry-After` header and the `error` "Too many failed sign-ins. Try again in N minutes." `authenticate()` isn't
  called while locked. The message is the same whether or not the account exists.
- A successful login clears the account's count, not the client's.
- The client address is `request.client.host`. Behind a reverse proxy, set `TRUSTED_PROXIES` so `register_core`'s
  proxy-headers middleware puts the real client there; otherwise every user shares the proxy's address. Override
  `client_address(request)` for another source.
- `InMemoryAttemptStore` suits a single process only. Call `throttle.prune()` now and then (e.g. from a scheduled
  job) to delete expired records.

**API logins.** A login route of the service's own, e.g. an OAuth2 token endpoint for its API, gets the same lockout
from `throttled_login`. Pass it the same `LoginThrottle` as `LoginViews`, so a guesser locked out of one can't carry
on at the other:

```python
from greentechhub_fastapi.auth import client_address, throttled_login

@router.post("/auth/login")
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    user = await throttled_login(throttle, form.username, lambda: check_password(form),
                                 address=client_address(request))
    if user is None:
        raise UnauthorizedError("Incorrect user ID or password")
    return {"access_token": issue_token(user), "token_type": "bearer"}
```

- It checks the lock first and raises `LoginLockedOut` (429, `Retry-After`, the same "Too many failed sign-ins"
  message) without calling the callable. A `None` result counts as a failure. Any other result clears the
  account's count and is returned.
- Under `register_api_error_handlers`' prefix the 429 comes back in the envelope, `code` `"too_many_requests"`.
- `address=None` counts by account only. `throttle=None` just runs the callable.

**Sign-up: `RegisterViews`** (`greentechhub_fastapi.auth.RegisterViews`) is the same idea for self-service sign-up:
`GET`/`POST /register`, with only storing the new user left to fill in:

```python
from greentechhub_core.security import hash_password
from greentechhub_fastapi.auth import RegisterViews, RegistrationError, resolve_dependency

class MyRegisterViews(RegisterViews):
    async def create_user(self, user_id: str, password: str) -> Identity:
        async with resolve_dependency(app, get_session) as session:
            if await session.get(User, user_id):
                raise RegistrationError({"user_id": ["That user ID is taken."]})
            session.add(User(id=user_id, password_hash=hash_password(password)))
            await session.commit()
        return Identity(subject=user_id, username=user_id, email=None, groups=[], claims={})

app.include_router(MyRegisterViews(templates=..., identity_provider=...).router())
```

- It checks the form first: a user ID (spaces trimmed), a password of at least `min_password_length` (8), and a
  matching `password_confirm`. Only then does it call `create_user`. Raise `RegistrationError({field: [message]})`
  for an expected refusal; let real failures propagate.
- A refused sign-up re-renders with status 422. A successful one signs the new user straight in, like a login: the
  session cookie, then the landing page (or `redirect_url`).
- `register_template` defaults to `"register_page.html"` (greentechhub-ui's sign-up page, in its release after
  v0.14; set your own template until you're on it). It gets `register_url`, `login_url` and
  `min_password_length` on every render, plus `errors` (`{field: [message]}`) and the submitted `user_id` after a
  refusal. The password is never sent back.
- `is_open(request)` decides whether sign-up is open. By default it's open while `signup_open` (`True`) is set and,
  when it's registered through `register_settings`, core's `self_signup_setting()` is on. That makes sign-up an
  app setting an admin can switch off from the settings page:

  ```python
  from greentechhub_core.settings.builtins import self_signup_setting

  register_settings(app, settings, registry=SettingsRegistry([
      self_signup_setting(edit_permission="settings.manage"),  # default=False for invite-only
  ]))
  ```

  `signup_open = False` closes sign-up whatever the setting says; override `is_open` for another rule, such as a
  feature flag. While closed, both routes answer 404. `settings.self_signup_open(request)` gives the same answer for
  your own routes.

**Asking for an email.** Set `ask_email = True` and the sign-up form also takes an email address, required unless
`require_email = False`, and checked for shape. The template gets `ask_email` (and the `email` back after a refusal),
and `create_user` is called with an `email` keyword (the address, or `None` when optional and left empty). Add
one when you turn this on. Pass `verification=` (your `EmailVerificationViews`, below) and the new
user is emailed a link to confirm the address; a mail problem is logged, not shown, since the account already
exists and the resend form can send it again:

```python
class MyRegisterViews(RegisterViews):
    ask_email = True
    sign_in_before_verified = False      # hold the sign-in back until they confirm

    async def create_user(self, user_id: str, password: str, email: str | None = None) -> Identity: ...

register = MyRegisterViews(templates=templates, identity_provider=provider, verification=verification)
```

With `sign_in_before_verified = False` the new user isn't signed in. The page instead gets `verify_sent`, `email`
and `verify_resend_url`, to say "check your email". Pair it with `LoginViews.refuse_sign_in` (below), so a sign-in
before confirming is turned away. The default (`True`) signs them in straight away and only sends the link.

**Password reset: `PasswordResetViews`** (`greentechhub_fastapi.auth.PasswordResetViews`) emails a single-use link
(greentechhub-core's `OneTimeTokens`) and lets the person choose a new password. Finding the account and storing the
password are left to fill in:

```python
from greentechhub_core.security import OneTimeTokens, hash_password
from greentechhub_core.sqlalchemy import SQLAlchemyTokenStore, one_time_tokens_table
from greentechhub_fastapi.auth import PasswordResetViews

class MyPasswordResetViews(PasswordResetViews):
    async def find_account(self, identifier: str) -> tuple[str, str] | None:
        async with resolve_dependency(app, get_session) as session:
            user = await find_user_by_id_or_email(session, identifier)
        return (user.id, user.email) if user is not None and user.email else None

    async def set_password(self, subject: str, password: str) -> None:
        async with resolve_dependency(app, get_session) as session:
            (await session.get(User, subject)).password_hash = hash_password(password)
            await session.commit()

tokens = OneTimeTokens(SQLAlchemyTokenStore(one_time_tokens_table(metadata), async_session_factory=async_session))
app.include_router(MyPasswordResetViews(templates=templates, tokens=tokens).router())
login_views.forgot_password_url = "/forgot-password"   # a "Forgot password?" link on the sign-in page
```

- It sends through [`register_email`](registration.md#email). Pass `base_url` there so the link is absolute.
- `GET`/`POST /forgot-password` takes a user ID or email. A matching account is emailed a link to
  `/reset-password/{token}`, valid for `token_lifetime` (an hour). **The page answers the same whether or not an
  account matched, and a mail problem is logged, not shown**, so it never reveals who has an account. Override
  `reset_email(address, link)` for your own wording.
- `GET`/`POST /reset-password/{token}` shows the "choose a new password" form, checks the length
  (`min_password_length`, 8) and the confirmation, then uses the token up and calls `set_password`. An unknown,
  expired or used link shows the invalid page (400). Requesting a new link revokes the older ones. The person isn't
  signed in: they sign in with the new password. Sessions already issued stay valid (stateless JWTs).
- Pass `throttle=LoginThrottle(...)` to cap reset emails per account and per client: every request counts, and a
  capped one gets 429 with `Retry-After` before any email.
- Templates default to greentechhub-ui's `forgot_password_page.html` and `reset_password_page.html` (still to come
  there). The forgot page gets `forgot_url` and `login_url`, plus `sent` and `identifier` after a request or `errors`
  (422). The reset page gets `action`, `login_url` and `min_password_length`, plus `errors` (422), `done`, or
  `invalid` with `forgot_url`.
- Call `tokens.prune()` now and then (e.g. from a scheduled job) to delete used and expired tokens.

**Email verification: `EmailVerificationViews`** (`greentechhub_fastapi.auth.EmailVerificationViews`) confirms that
an address belongs to the person who gave it, with an emailed single-use link. Recording that it's confirmed, and
finding who still needs to confirm, are left to fill in:

```python
from greentechhub_fastapi.auth import EmailVerificationViews

class MyEmailVerificationViews(EmailVerificationViews):
    async def mark_verified(self, subject: str) -> None:
        async with resolve_dependency(app, get_session) as session:
            (await session.get(User, subject)).email_verified = True
            await session.commit()

    async def find_unverified(self, identifier: str) -> tuple[str, str] | None:
        async with resolve_dependency(app, get_session) as session:
            user = await find_user_by_id_or_email(session, identifier)
        ok = user is not None and user.email and not user.email_verified
        return (user.id, user.email) if ok else None

verification = MyEmailVerificationViews(templates=templates, tokens=tokens)   # OneTimeTokens, as for reset
app.include_router(verification.router())

# wherever the service sets an address: its own sign-up, or SettingsViews' save_profile
await verification.send_link(request, user.id, user.email)
```

- `send_link(request_or_app, subject, address)` emails a link to `/verify-email/{token}`, valid for
  `token_lifetime` (48 hours), through [`register_email`](registration.md#email). Mail errors propagate, so the
  caller knows. A new link revokes the older ones. Override `verify_email(address, link)` for your own wording.
- `GET /verify-email/{token}` uses the link up and calls `mark_verified`. It runs on a GET so one click is enough. A
  mail scanner that prefetches the link only confirms the address the person gave. An unknown, expired or used link
  shows the invalid page (400), which links to the resend form.
- `GET`/`POST /verify-email/resend` takes a user ID or email and sends a new link to an account that still needs
  confirming. As with password reset, the page is the same whether or not one matched, mail problems are logged,
  and `throttle=` caps the emails (429 with `Retry-After`).
- Templates default to greentechhub-ui's `verify_email_page.html` and `verify_email_resend_page.html` (still to come
  there). The link page gets `login_url` plus `done`, or `invalid` and `resend_url`. The resend page gets
  `resend_url` and `login_url`, plus `sent` and `identifier`, or `errors`.

**Gating sign-in.** To keep unconfirmed accounts out, override `LoginViews.refuse_sign_in(identity)`. A message it
returns re-renders the sign-in page as the `error`, with status 403 and no session. Set `verify_resend_url` (e.g.
`"/verify-email/resend"`) and that page also gets it, to offer the link again:

```python
class MyLoginViews(LoginViews):
    verify_resend_url = "/verify-email/resend"

    async def refuse_sign_in(self, identity: Identity) -> str | None:
        user = await load_user(identity.subject)
        return None if user.email_verified else "Confirm your email address first."
```

**CSRF (opt-in).** Set `csrf = True` on any of `LoginViews`, `RegisterViews`, `PasswordResetViews` and
`EmailVerificationViews` to check a CSRF token on their forms' POSTs:

```python
class MyLoginViews(LoginViews):
    csrf = True
```

- It's a double-submit cookie, which fits the stateless sessions. A form's page sets a random token as the `gth_csrf`
  cookie (httponly, secure, samesite=lax, like the session cookie) and passes the same token to the template as
  `csrf_token`. The POST must send it back as the `csrf_token` field. A page on another site can't read the cookie,
  so it can't forge the field. The token is reused across pages, so the back button and a second tab keep working.
- greentechhub-ui v0.15+ renders the field on every auth page (`gth_csrf_field`). A template of your own adds
  `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` inside the form.
- The check runs first, before the throttle, `authenticate` or anything else. A missing or wrong token re-renders
  the page with status 403 and "Your session expired. Please try again." (`error` on the sign-in page; `errors`
  under `__all__`, or under `identifier` on the forgot and resend forms), with a fresh token, and nothing else
  happens: no sign-in, no user created, no email sent, no reset link used up.
- Not covered: `POST /logout` (signing someone out is low-risk, and the navbar's logout form has no token), the
  emailed links (plain GETs), and your own htmx forms, which can send a token in `hx-headers` and check it
  themselves.
- Over plain HTTP the secure cookie isn't sent back, so every checked POST is refused. Leave `csrf` off for
  local HTTP testing, as the session cookie already needs HTTPS.

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
