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

See [docs/auth.md](auth.md), [docs/health.md](health.md), and [docs/modules.md](modules.md) for what each `register_*` call actually wires up.
