"""admin — the "Admin" nav group for a service's admin pages (register_admin
mounts the pages and returns it).

Each admin view (RoleAdminViews, AuditViews, or a service's own) becomes one
child: its title, url and icon, with its permission as required_permission.
greentechhub-ui's nav filtering (navigation.filter_by_scope, per request
through nav_visible) then hides the pages a viewer can't open, and the group
itself when none are left, since it has no url of its own. Plain dicts, so
this package still doesn't import greentechhub-ui.
"""

from collections.abc import Iterable
from typing import Any, Protocol

from fastapi import APIRouter


class AdminView(Protocol):
    """What register_admin needs from an admin page: RoleAdminViews and
    AuditViews have it, and so can a service's own."""

    url: str
    title: str
    icon: str
    permission: str

    def router(self) -> APIRouter: ...


def admin_nav_item(
    views: Iterable[AdminView], *, label: str = "Admin", icon: str = "gear"
) -> dict[str, Any]:
    """A greentechhub-ui NavItem group with one child per view, in order."""
    return {
        "label": label,
        "icon": icon,
        "children": [
            {"label": view.title, "url": view.url, "icon": view.icon,
             "required_permission": view.permission}
            for view in views
        ],
    }
