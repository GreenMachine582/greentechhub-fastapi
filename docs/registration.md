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

`register_settings` returns the `Settings` it built. A malformed env override, a malformed `manage_permission`, or a
`manage_permission` without `register_permissions` fails at startup. Call it before the app starts.

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

**The page (`SettingsViews`).**

| Route | Does |
|---|---|
| `GET /settings` | Preferences (the registry's USER settings) for any signed-in user; App (its APP settings) too when they hold `manage_permission`. Anonymous → login redirect |
| `POST /settings/preferences` | coerce each field; 422 with the section and its errors, or save and return the section with a toast (plus `gth:theme` when the theme changed) |
| `POST /settings/app` | the same for APP settings; 403 without `manage_permission` |
| `POST /settings/theme` | the theme toggle's save (`theme=light\|dark`): 204, 401 anonymous, 422 invalid |

- A preference saved equal to what the user would get anyway (the app value, env override or default) resets their
  own value instead of storing it, so saving an untouched form doesn't pin today's defaults.
- Subclass to change `url`, `login_url`, `title`, the section titles/descriptions, or `page_template` /
  `section_template` to use your own templates (they get `settings_sections` / `section`, see greentechhub-ui's
  docs/components.md).
- Dependencies for your own routes, in `greentechhub_fastapi.settings`: `get_settings_service` (the `Settings`) and
  `get_effective_settings` (the current user's values).

See [docs/auth.md](auth.md), [docs/health.md](health.md), and [docs/modules.md](modules.md) for what each `register_*` call actually wires up.
