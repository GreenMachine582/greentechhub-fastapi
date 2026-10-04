"""greentechhub-fastapi: the FastAPI/Starlette adapter package for the
GreenTechHub ecosystem.

Unlike greentechhub_core's root __init__.py (a docstring only — that package
imports its modules explicitly), this root re-exports the register_* functions,
matching docs/registration.md's own usage example:
    from greentechhub_fastapi import (
        register_core, register_logging, register_health,
        register_exception_handlers, register_auth,
    )

register_exception_handlers (and register_api_error_handlers) come from
greentechhub_fastapi.exceptions rather than greentechhub_fastapi.registration —
neither has a registration/*.py wrapper,
since docs/exceptions.md's own usage example imports it directly from its
module, unlike register_health/register_core/register_logging/register_auth.

PageParams (from greentechhub_fastapi.query), and get_current_user /
get_current_identity / the session-cookie helpers (from
greentechhub_fastapi.auth / greentechhub_fastapi.dependencies), are
deliberately not re-exported here: they're per-route Depends() dependencies
or route-local helpers, not one-time app-level registration calls, and each
module's own doc sample imports them directly from their own module.

register_auth implements both the "local" and "forward_auth" adapters
(docs/auth.md) as of v0.5 — AUTH_ADAPTER selects between them as a config
change, not a code change.

register_flash / register_events (v0.4) join the other register_* functions
here for the same reason: each is a one-time app-level registration call. The
functions they enable at each request — flash()/get_flashes() (flash.py),
get_event_publisher() (events.py) — stay un-re-exported, same as
get_current_user/get_current_identity, since they're per-route Depends()
dependencies, not registration calls.

register_permissions joins them on the same grounds; its per-route
dependencies (get_granted_permissions, require_permission,
require_page_permission in greentechhub_fastapi.permissions) stay
un-re-exported.

register_settings likewise; SettingsViews, settings_context and the
get_settings_service / get_effective_settings dependencies live in
greentechhub_fastapi.settings.

register_notifications likewise; notify, NotificationViews,
notifications_nav_item and get_notification_store live in
greentechhub_fastapi.notifications.
"""

from greentechhub_fastapi.exceptions import register_api_error_handlers, register_exception_handlers
from greentechhub_fastapi.registration import (
    register_auth,
    register_core,
    register_events,
    register_flash,
    register_health,
    register_logging,
    register_notifications,
    register_permissions,
    register_settings,
)

__all__ = [
    "register_api_error_handlers",
    "register_auth",
    "register_core",
    "register_events",
    "register_exception_handlers",
    "register_flash",
    "register_health",
    "register_logging",
    "register_notifications",
    "register_permissions",
    "register_settings",
]
