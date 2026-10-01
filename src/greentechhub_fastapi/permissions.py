"""permissions — the route-local Depends counterparts to
registration.permissions.register_permissions.

- get_permission_resolver: the PermissionResolver register_permissions put
  on the app.
- get_granted_permissions: the current user's granted permissions, resolved
  once per request however many checks a route runs.
- require_permission(p): JSON routes. Anonymous → UnauthorizedError (401
  envelope), signed in without `p` → ForbiddenError (403 envelope), both via
  register_exception_handlers like get_current_identity.
- require_page_permission(p): page routes. Anonymous gets
  require_page_identity's redirect (303, or 401 + HX-Redirect for HTMX);
  signed in without `p` gets a plain 403 HTTPException, which a service can
  restyle with its own HTTPException handler.

Both require_* builders return the Identity, so a route that needs the user
anyway can take it from the same dependency. The permission string is
checked with core's Permission() when the dependency is built, so a typo
fails at import time rather than denying everyone at request time.

Holds no permission values of its own: the service passes its Roles (or a
whole resolver) to register_permissions, as core's docs/permissions.md
requires.
"""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request
from greentechhub_core.identity import Identity
from greentechhub_core.permissions import Permission, PermissionResolver
from greentechhub_core.types import ForbiddenError, UnauthorizedError

from greentechhub_fastapi.auth.dependency import get_current_user
from greentechhub_fastapi.dependencies.identity import require_page_identity

RESOLVER_STATE_KEY = "gth_permission_resolver"
_GRANTED_STATE_KEY = "gth_granted_permissions"


def get_permission_resolver(request: Request) -> PermissionResolver:
    resolver = getattr(request.app.state, RESOLVER_STATE_KEY, None)
    if resolver is None:
        raise RuntimeError("no permission resolver: call register_permissions(app, ...) first")
    return resolver


async def get_granted_permissions(
    request: Request,
    user: Identity | None = Depends(get_current_user),
    resolver: PermissionResolver = Depends(get_permission_resolver),
) -> frozenset[Permission]:
    """Every permission the current user holds; empty for anonymous."""
    cached = getattr(request.state, _GRANTED_STATE_KEY, None)
    if cached is not None:
        return cached
    granted = await resolver.granted(user)
    setattr(request.state, _GRANTED_STATE_KEY, granted)
    return granted


def require_permission(permission: str) -> Callable[..., Awaitable[Identity]]:
    """Build a dependency that lets a JSON route through only when the
    caller holds `permission`. Usage:
    `APIRouter(dependencies=[Depends(require_permission("reports.view"))])`.
    """
    required = Permission(permission)

    async def dependency(
        user: Identity | None = Depends(get_current_user),
        granted: frozenset[Permission] = Depends(get_granted_permissions),
    ) -> Identity:
        if user is None:
            raise UnauthorizedError("authentication required")
        if required not in granted:
            raise ForbiddenError(f"missing permission {required!s}")
        return user

    return dependency


def require_page_permission(
    permission: str, login_url: str = "/login"
) -> Callable[..., Awaitable[Identity]]:
    """The page-route twin of require_permission: anonymous callers are sent
    to `login_url` (see require_page_identity), callers without
    `permission` get a 403.
    """
    required = Permission(permission)
    page_identity = require_page_identity(login_url)

    async def dependency(
        user: Identity = Depends(page_identity),
        granted: frozenset[Permission] = Depends(get_granted_permissions),
    ) -> Identity:
        if required not in granted:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return dependency
