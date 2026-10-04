[← Back to README](../README.md)

# 🔌 Service Registration

Wiring middleware and dependencies by hand, service by service, doesn't scale. This package makes registration explicit and one-line-per-concern instead:

```python
from fastapi import FastAPI
from greentechhub_fastapi import register_core, register_logging, register_health, register_auth

app = FastAPI()
register_logging(app, settings)
register_core(app, settings)      # request-id, timing, security headers, CORS
register_health(app, checks=[check_database])
register_auth(app, settings)      # picks local vs. forward_auth from settings.auth_adapter
```

CORS is bundled into `register_core` rather than a separate call — it reads allowed origins from a `CORS_ALLOWED_ORIGINS`-style field on the service's `Settings`, defaulting to empty/restrictive so a service is safe out of the box and one env var away from configured.

Each `register_*` function is small and composable — a service can skip ones it doesn't need (a pure internal API might skip `register_auth`) rather than getting an all-or-nothing bundle.

A service's own `Settings` still extends `greentechhub-core`'s `GTHBaseSettings` directly:

```python
from greentechhub_core.config import GTHBaseSettings

class Settings(GTHBaseSettings):
    ASYNC_DATABASE_URL: str
```

`greentechhub-core` is still imported directly for pure contracts (`Settings`, `Page`, `ApplicationError`) — only the framework-touching pieces route through this package.

## Permissions

`register_permissions` is opt-in: nothing checks permissions until a service calls it and puts a `require_*`
dependency on a route. It builds `greentechhub-core`'s `RoleResolver` from the service's own roles, so this package
still defines no permission values.

```python
from greentechhub_core.permissions import Permission, Role
from greentechhub_fastapi import register_auth, register_permissions
from greentechhub_fastapi.permissions import require_page_permission, require_permission

ADMIN = Role(name="admin", permissions={Permission("settings.manage")})

register_auth(app, settings)
register_permissions(app, settings, roles=[ADMIN])      # optional: grants=GrantStore, or resolver=...

@router.get("/api/admin/stats")
async def stats(user=Depends(require_permission("settings.manage"))): ...      # 401 / 403 JSON envelope

@router.get("/admin")
async def admin_page(user=Depends(require_page_permission("settings.manage"))): ...  # login redirect / 403
```

Two optional settings feed the built resolver, read tolerantly like `CORS_ALLOWED_ORIGINS`:

| Setting | Maps | Example |
|---|---|---|
| `ROLE_GROUPS` | directory group → roles | `staff=viewer,admins=admin` |
| `ROLE_BOOTSTRAP` | subject → roles, for the first admin and recovery | `alice=admin` |

- Each takes the compact form above (several roles joined with `|`: `alice=admin|editor`), a JSON object string, or a
  mapping (a `dict[str, list[str]]` field on the service's `Settings`). Unset means no entries.
- A bootstrap subject is all a service on `AUTH_ADAPTER=local` needs for its first admin; no Authentik groups are
  involved. A role name not in `roles` fails at startup.
- `resolver=` takes any core `PermissionResolver` instead; `roles`/`grants` can't be passed with it.
  `register_permissions` returns the resolver it installed.

| Dependency | Anonymous | Signed in, missing the permission |
|---|---|---|
| `require_permission(p)` | 401 envelope (`UnauthorizedError`) | 403 envelope (`ForbiddenError`) |
| `require_page_permission(p, login_url="/login")` | 303 to `login_url`, or 401 + `HX-Redirect` for HTMX | plain 403 |
| `get_granted_permissions` | empty set | the caller's permissions |

Both `require_*` builders return the `Identity`, validate `p` when they're built, and share one resolver lookup per
request. The JSON envelopes need `register_exception_handlers`.

### Role assignments

`RoleAdminViews` is an admin page over the `GrantStore` passed to `register_permissions`: it lists in-app role grants
and assigns, changes and removes them. It renders greentechhub-ui's ready-made `roles_page.html` /
`roles_section.html` by default and passes data only, so this package still doesn't import greentechhub-ui.

```python
from greentechhub_core.sqlalchemy import SQLAlchemyGrantStore, role_grants_table
from greentechhub_fastapi.permissions import RoleAdminViews

grants = SQLAlchemyGrantStore(role_grants_table(Base.metadata), async_session_factory=Session)
register_permissions(app, settings, roles=ROLES, grants=grants)   # ROLE_BOOTSTRAP=alice=admin
app.include_router(RoleAdminViews(templates=templates, permission="users.manage").router())
```

| Route (`url` = `/admin/roles`) | Does |
|---|---|
| `GET {url}` | the page: every grant (`list_assignments`), with the service's roles as choices |
| `POST {url}` | assign the checked roles to `subject`; 422 with errors for a blank subject or no roles |
| `POST {url}/{subject}` | make the subject's roles exactly the checked ones (`assign` the new, `revoke` the rest) |
| `DELETE {url}/{subject}` | revoke all of the subject's roles |

- Every route needs `permission`, through `require_page_permission`: anonymous visitors go to `login_url`, users
  without it get 403. Each write returns the section with a toast, which greentechhub-ui's section swaps in place.
- Subjects are path segments, so one containing `/` is sent as `%2F`; the route accepts it.
- Only known role names are assigned. A stored name that isn't in `roles` (a role deleted from code) grants nothing,
  isn't shown, and is left alone by a change; a remove revokes it too.
- Only grants are listed. Roles from `ROLE_GROUPS` or `ROLE_BOOTSTRAP` are configuration, which is also the recovery
  path if an admin removes their own grant.
- With `register_permissions(..., resolver=...)` there are no `roles`/`grants` to read, so pass them:
  `RoleAdminViews(..., roles=ROLES, grants=grants)`. Without a `GrantStore` the page raises a `RuntimeError` naming
  what's missing. Subclass to change `url`, `login_url`, `title` or the template names.

## Settings

`register_settings` puts `greentechhub-core`'s `Settings` on the app and, with `views`, mounts a working `/settings`
page. It's opt-in, works with `AUTH_ADAPTER=local` alone, and doesn't import greentechhub-ui: it passes data, and
`SettingsViews` renders greentechhub-ui's ready-made `settings_page.html` / `settings_section.html` by default.

```python
from greentechhub_core.settings import JsonFileSettingsStore, SettingsRegistry
from greentechhub_core.settings.builtins import USER_PREFERENCES
from greentechhub_fastapi import register_auth, register_permissions, register_settings
from greentechhub_fastapi.settings import SettingsViews, settings_context
from greentechhub_fastapi.templating import ui_context

templates = Jinja2Templates(directory="templates", context_processors=[ui_context, settings_context])
greentechhub_ui.install(templates.env, service_name="…", nav_items=[…])

register_auth(app, settings)
register_permissions(app, settings, roles=[ADMIN])        # ROLE_BOOTSTRAP=alice=admin for the first admin
register_settings(
    app, settings,
    registry=SettingsRegistry([*USER_PREFERENCES, BANNER]),
    store=JsonFileSettingsStore("data/settings.json"),    # or core's SQLAlchemySettingsStore
    views=SettingsViews(templates=templates),             # optional: the /settings page
    manage_permission="settings.manage",                  # optional: the App section
    logout_url="/logout",                                 # optional: the user menu's Log out
)
```

`register_settings` returns the `Settings` it built. A malformed env override, a malformed `manage_permission`, a
`manage_permission` without `register_permissions`, or a secret setting without a `cipher` fails at startup. Call it
before the app starts.

**Secret settings.** A credential (an email app password, an API token) is a core `Setting(..., secret=True)`:
encrypted at rest, write-only on the page. Pass a cipher, from core's `[crypto]` extra
(`pip install 'greentechhub-core[crypto]'`), with its key kept in your config, never in the store:

```python
from greentechhub_core.settings.crypto import FernetCipher   # FernetCipher.generate_key() makes a key

register_settings(app, settings, registry=registry, store=store, views=SettingsViews(templates=templates),
                  cipher=FernetCipher(settings.SETTINGS_CIPHER_KEY))
```

- A registry with a secret setting and no `cipher` fails at startup.
- Secrets only ever reach a template or a JSON value as core's `SECRET_SET` marker (or `None` when unset):
  `user_settings`, the sections' `values` and `get_effective_settings` all carry the marker, and a 422 never echoes
  a submitted secret. greentechhub-ui (v0.13+) renders the field as an always-empty password input.
- On save, a blank field keeps the stored value, `<key>.__clear=true` resets it, and anything else is the new value
  (core encrypts it). APP secrets still need `manage_permission` and their own `edit_permission`.
- Server code reads the plaintext through `get_secret(key)`, a dependency factory: the user's value, else the app
  value, else `None`. It raises core's `SecretDecryptError` if the cipher key changed since the value was saved.

```python
from greentechhub_fastapi.settings import get_secret

@app.post("/emails/sync")
async def sync(password: str | None = Depends(get_secret("email.app_password"))): ...
```

**Landing page.** Register core's `landing_page_setting` and each person picks the page they land on after logging
in. It shows on `/settings` under Navigation like any choice setting:

```python
from greentechhub_core.settings.builtins import USER_PREFERENCES, landing_page_setting

registry = SettingsRegistry([
    *USER_PREFERENCES,
    landing_page_setting({"/": "Dashboard", "/reports": "Reports"}, default="/"),
])
```

- `LoginViews` then redirects a successful login to the user's choice (else the app value or the setting's default)
  instead of `redirect_url`. Without `register_settings`, or without the setting, `redirect_url` applies as before.
- `landing_url(request, identity, *, fallback="/")` (async, `greentechhub_fastapi.settings`) gives the same page for
  your own routes, e.g. a `/home` that isn't itself one of the choices. `fallback` applies when the setting isn't
  registered.
- The page is always one of the setting's choices (core validates it, and a stored page later removed from the
  choices falls back to the default), so it's never an open redirect. `/` is never redirected automatically, since it
  may itself be a choice.

**Self-service sign-up.** With core's `self_signup_setting()` in the registry, `RegisterViews` closes its routes and
`LoginViews` hides its "Create account" link while the app value is off. `self_signup_open(request, *,
fallback=True)` (async, `greentechhub_fastapi.settings`) gives the same answer for your own routes. See
[auth.md](auth.md) for details.

**Page context.** `register_settings` adds `SettingsContextMiddleware` (innermost, after proxy headers and auth). For
page requests (`Accept: text/html`, or an htmx request) it resolves the user, their granted permissions and their
effective settings once; JSON and static requests skip it. `settings_context`, a `Jinja2Templates` context
processor, turns that into greentechhub-ui's optional template keys:

| Key | When |
|---|---|
| `current_user`, `user_settings` | every page request (`user_settings`: the effective values, e.g. `ui.page_size`) |
| `granted` | when `register_permissions` ran |
| `theme_mode` | signed in, and `ui.theme` is registered |
| `theme_save_url`, `user_menu_items` (Settings) | signed in, and `views` were mounted |
| `logout_url` | signed in, and `logout_url` was given |
| `site_banners` | core's `site_banner_settings()` is registered and the message isn't empty: any visitor, signed in or not |

**Site banner.** Register core's banner settings and every page shows the message above the navbar once someone sets
it, for example in Settings › App:

```python
from greentechhub_core.settings.builtins import USER_PREFERENCES, site_banner_settings

registry = SettingsRegistry([*USER_PREFERENCES, *site_banner_settings(edit_permission="settings.manage")])
register_settings(app, settings, registry=registry, store=store, views=SettingsViews(templates=templates),
                  manage_permission="settings.manage")
```

`settings_context` passes it as greentechhub-ui's `site_banners`: `[{"message", "tone", "id": "site"}]`. The tone
defaults to `warn`, and the fixed id means a dismissed banner shows again when its message changes. An `env` passed to
`register_settings` (e.g. `registry.env_overrides()`) applies too, so a banner can be put up without the UI. A service that builds its own `site_banners` should merge them,
since a later context processor's key replaces this one's.

**The page (`SettingsViews`).**

| Route | Does |
|---|---|
| `GET /settings` | Preferences (the registry's USER settings) for any signed-in user; App (its APP settings) too when they hold `manage_permission`. Anonymous → login redirect |
| `POST /settings/preferences` | coerce each field; 422 with the section and its errors, or save and return the section with a toast (plus `gth:theme` when the theme changed) |
| `POST /settings/app` | the same for APP settings; 403 without `manage_permission` |
| `POST /settings/theme` | the theme toggle's save (`theme=light\|dark`): 204, 401 anonymous, 422 invalid |
| `POST /settings/password` | only with `change_password=`: change the signed-in user's password (below) |

- A preference saved equal to what the user would get anyway (the app value, env override or default) resets their
  own value instead of storing it, so saving an untouched form doesn't pin today's defaults.
- Subclass to change `url`, `login_url`, `title`, the section titles/descriptions, or `page_template` /
  `section_template` to use your own templates (they get `settings_sections` / `section`, see greentechhub-ui's
  docs/components.md).
- **Change password** (opt-in): pass `change_password`, an async `(user, current, new) -> bool` that returns `False`
  when `current` isn't the user's password and otherwise stores `new` (hashing it is yours, as with `LoginViews`).
  The page then shows a Password section after Preferences. Its route first checks the fields: the current password
  is given, the new one has at least `min_password_length` (8) characters, differs from the current one and is
  confirmed. It then calls yours: 422 with the section's errors, or 200 with an empty section and a "Password
  changed" toast. The fields are write-only secret fields, so greentechhub-ui's settings templates render them as
  empty password inputs and nothing is filled back in. Sessions already issued stay valid (they're stateless JWTs).

  ```python
  async def change_password(user: Identity, current: str, new: str) -> bool:
      async with resolve_dependency(app, get_session) as session:
          row = await session.get(User, user.subject)
          if row is None or not verify_password(current, row.password_hash):
              return False
          row.password_hash = hash_password(new)
          await session.commit()
      return True

  views = SettingsViews(templates=templates, change_password=change_password)
  ```
- Dependencies for your own routes, in `greentechhub_fastapi.settings`: `get_settings_service` (the `Settings`),
  `get_effective_settings` (the current user's values, secrets as the marker) and `get_secret(key)` (a secret's
  plaintext).

See [docs/auth.md](auth.md), [docs/health.md](health.md), and [docs/modules.md](modules.md) for what each `register_*` call actually wires up.
