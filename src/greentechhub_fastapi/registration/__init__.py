from greentechhub_fastapi.registration.auth import register_auth
from greentechhub_fastapi.registration.core import register_core
from greentechhub_fastapi.registration.events import register_events
from greentechhub_fastapi.registration.flash import register_flash
from greentechhub_fastapi.registration.health import register_health
from greentechhub_fastapi.registration.logging import register_logging
from greentechhub_fastapi.registration.notifications import register_notifications
from greentechhub_fastapi.registration.permissions import register_permissions
from greentechhub_fastapi.registration.settings import register_settings

__all__ = [
    "register_auth",
    "register_core",
    "register_events",
    "register_flash",
    "register_health",
    "register_logging",
    "register_notifications",
    "register_permissions",
    "register_settings",
]
