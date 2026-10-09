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

- RoleAdminViews: an admin page over the GrantStore — list in-app role
  grants, assign, set and remove them — gated on a permission the service
  supplies. Renders greentechhub-ui's roles_page.html / roles_section.html
  by default, passing data only.

Holds no permission values of its own: the service passes its Roles (or a
whole resolver) to register_permissions, as core's docs/permissions.md
requires.
"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import Identity
from greentechhub_core.permissions import GrantStore, Permission, PermissionResolver, Role
from greentechhub_core.types import ForbiddenError, UnauthorizedError

from greentechhub_fastapi.auth.dependency import get_current_user
from greentechhub_fastapi.dependencies.identity import require_page_identity
from greentechhub_fastapi.htmx import _toast_trigger

RESOLVER_STATE_KEY = "gth_permission_resolver"
ROLES_STATE_KEY = "gth_permission_roles"
GRANTS_STATE_KEY = "gth_grant_store"
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


class RoleAdminViews:
    """The role assignment admin page. Mount it like LoginViews:
    `app.include_router(RoleAdminViews(templates=templates,
    permission="users.manage").router())`.

    It edits the GrantStore and offers the Roles that register_permissions
    was given (`roles=`, `grants=`); pass `roles`/`grants` here instead when
    the app was given a ready `resolver=`. Every route needs `permission`
    (see require_page_permission: anonymous → login, missing → 403).

    GET {url}: the page. POST {url}: assign the checked roles to a subject.
    POST {url}/{subject}: make that subject's roles exactly the checked ones.
    DELETE {url}/{subject}: remove all of them. Each write returns the
    section (422 with errors for a blank subject or no roles) and a toast.

    `csrf=True` checks every write with require_csrf (403 without the
    token); it needs register_csrf so the page carries one.

    Only grants are listed and edited: roles from directory groups or
    ROLE_BOOTSTRAP are configuration. That's also the recovery path if an
    admin removes their own grant. Stored role names that aren't in the
    catalogue grant nothing; a set leaves them alone.
    """

    page_template: str = "roles_page.html"
    section_template: str = "roles_section.html"
    url: str = "/admin/roles"
    login_url: str = "/login"
    title: str = "Roles"

    def __init__(
        self,
        *,
        templates: Jinja2Templates,
        permission: str,
        roles: Iterable[Role] | None = None,
        grants: GrantStore | None = None,
        csrf: bool = False,
    ) -> None:
        self._templates = templates
        self._guard = require_page_permission(permission, self.login_url)
        self.csrf = csrf
        self._roles = tuple(roles) if roles is not None else None
        self._grants = grants

    def router(self) -> APIRouter:
        # Imported here: auth's package __init__ imports views, which import this module.
        from greentechhub_fastapi.auth.csrf import require_csrf

        router = APIRouter(dependencies=[Depends(require_csrf)] if self.csrf else [])
        guard = self._guard

        async def page(request: Request, user: Identity = Depends(guard)):
            return self._templates.TemplateResponse(
                request, self.page_template,
                {"page_title": self.title, **await self._context(request)},
            )

        async def assign(request: Request, user: Identity = Depends(guard)):
            return await self._assign(request)

        async def set_roles(request: Request, subject: str, user: Identity = Depends(guard)):
            return await self._set(request, subject)

        async def remove(request: Request, subject: str, user: Identity = Depends(guard)):
            return await self._remove(request, subject)

        router.add_api_route(self.url, page, methods=["GET"])
        router.add_api_route(self.url, assign, methods=["POST"])
        # :path so a subject containing "/" (sent as %2F) still matches
        router.add_api_route(f"{self.url}/{{subject:path}}", set_roles, methods=["POST"])
        router.add_api_route(f"{self.url}/{{subject:path}}", remove, methods=["DELETE"])
        return router

    # data

    def _catalogue(self, request: Request) -> tuple[Role, ...]:
        if self._roles is not None:
            return self._roles
        return getattr(request.app.state, ROLES_STATE_KEY, ())

    def _store(self, request: Request) -> GrantStore:
        store = self._grants or getattr(request.app.state, GRANTS_STATE_KEY, None)
        if store is None:
            raise RuntimeError(
                "RoleAdminViews needs a GrantStore: register_permissions(..., grants=...) "
                "or RoleAdminViews(..., grants=...)"
            )
        return store

    async def _context(self, request: Request, **extra: Any) -> dict[str, Any]:
        assignments = await self._store(request).list_assignments()
        return {
            "roles_url": self.url,
            "roles_assignments": [
                {"subject": subject, "roles": sorted(roles)}
                for subject, roles in sorted(assignments.items())
            ],
            "roles_options": [{"value": r.name, "label": r.name} for r in self._catalogue(request)],
            **extra,
        }

    def _known(self, request: Request, names: Iterable[str]) -> list[str]:
        known = [r.name for r in self._catalogue(request)]
        picked = set(names)
        return [name for name in known if name in picked]

    async def _section(self, request: Request, message: str | None = None, **extra: Any):
        headers = {"HX-Trigger": _toast_trigger(message)} if message else None
        status_code = 422 if "roles_form" in extra else 200
        return self._templates.TemplateResponse(
            request, self.section_template, await self._context(request, **extra),
            status_code=status_code, headers=headers,
        )

    # writes

    async def _assign(self, request: Request):
        form = await request.form()
        subject = str(form.get("subject") or "").strip()
        roles = self._known(request, (str(r) for r in form.getlist("roles")))
        errors: dict[str, list[str]] = {}
        if not subject:
            errors["subject"] = ["Enter a user ID."]
        if not roles:
            errors["roles"] = ["Pick at least one role."]
        if errors:
            return await self._section(
                request, roles_form={"subject": subject, "roles": roles, "errors": errors}
            )
        store = self._store(request)
        for role in roles:
            await store.assign(subject, role)
        return await self._section(request, f"Roles assigned to {subject}")

    async def _set(self, request: Request, subject: str):
        form = await request.form()
        wanted = set(self._known(request, (str(r) for r in form.getlist("roles"))))
        known = {r.name for r in self._catalogue(request)}
        store = self._store(request)
        held = await store.roles_for(subject)
        for role in wanted - held:
            await store.assign(subject, role)
        for role in (held & known) - wanted:  # unknown stored names are left alone
            await store.revoke(subject, role)
        return await self._section(request, f"Roles saved for {subject}")

    async def _remove(self, request: Request, subject: str):
        store = self._store(request)
        for role in await store.roles_for(subject):
            await store.revoke(subject, role)
        return await self._section(request, f"Removed {subject}'s roles")
