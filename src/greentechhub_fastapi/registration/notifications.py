"""register_notifications — puts greentechhub-core's NotificationStore on the
app for notify(), and optionally mounts the notification centre's routes.

Opt-in like every register_* call. It:
  - stores the NotificationStore on app.state, where notify() and
    get_notification_store find it;
  - mounts `views` (a NotificationViews) when given.

Delivery preferences need nothing here: register core's
notification_preferences(...) settings through register_settings and
notify() follows them.
"""

from typing import Any

from fastapi import FastAPI
from greentechhub_core.notifications import NotificationStore

from greentechhub_fastapi.notifications import (
    NOTIFICATIONS_STATE_KEY,
    NotificationsConfig,
    NotificationViews,
)


def register_notifications(
    app: FastAPI,
    settings: Any,
    *,
    store: NotificationStore,
    views: NotificationViews | None = None,
) -> NotificationStore:
    """Install the app's NotificationStore and return it. `settings` is the
    service's GTHBaseSettings, accepted for symmetry with the other
    register_* calls."""
    if app.middleware_stack is not None:
        raise RuntimeError("register_notifications must run before the app starts")
    setattr(
        app.state,
        NOTIFICATIONS_STATE_KEY,
        NotificationsConfig(store=store, url=views.url if views is not None else None),
    )
    if views is not None:
        app.include_router(views.router())
    return store
