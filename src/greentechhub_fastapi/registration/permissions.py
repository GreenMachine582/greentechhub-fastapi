"""register_permissions — puts a PermissionResolver on the app for
permissions.get_granted_permissions / require_permission to use.

Opt-in like every register_* call: nothing checks permissions until a
service calls this and adds a require_* dependency to a route.

Either pass a ready `resolver` (any core PermissionResolver), or pass the
service's `roles` (and optionally a GrantStore as `grants`) and let this
build core's RoleResolver, with its group and bootstrap maps read
tolerantly from two optional settings:

    ROLE_GROUPS     directory group → role names
    ROLE_BOOTSTRAP  subject → role names, for the first admin and recovery

Each setting may be a mapping (a pydantic `dict[str, list[str]]` field), a
JSON object string, or the compact env form
`"alice=admin|editor,bob=viewer"`. Missing or empty means no entries. A
bootstrap subject works with AUTH_ADAPTER=local alone; no Authentik
groups are needed. RoleResolver fails fast on a map naming an unknown
role, so a typo in either setting surfaces at startup.
"""

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from greentechhub_core.permissions import (
    GrantStore,
    PermissionResolver,
    Role,
    RoleResolver,
    read_role_map,
)

from greentechhub_fastapi.permissions import (
    GRANTS_STATE_KEY,
    RESOLVER_STATE_KEY,
    ROLES_STATE_KEY,
)


def register_permissions(
    app: FastAPI,
    settings: Any,
    *,
    roles: Iterable[Role] = (),
    grants: GrantStore | None = None,
    resolver: PermissionResolver | None = None,
) -> PermissionResolver:
    """Install the app's PermissionResolver and return it (handy for
    register_settings, or a sync tool sharing the same resolver)."""
    roles = tuple(roles)
    if resolver is not None:
        if roles or grants is not None:
            raise ValueError("pass either resolver, or roles/grants to build one — not both")
    else:
        resolver = RoleResolver(
            roles=roles,
            group_roles=read_role_map(settings, "ROLE_GROUPS"),
            bootstrap=read_role_map(settings, "ROLE_BOOTSTRAP"),
            grants=grants,
        )
    setattr(app.state, RESOLVER_STATE_KEY, resolver)
    # For RoleAdminViews: the catalogue it offers and the store it edits.
    setattr(app.state, ROLES_STATE_KEY, roles)
    setattr(app.state, GRANTS_STATE_KEY, grants)
    return resolver
