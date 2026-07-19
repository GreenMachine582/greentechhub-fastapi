"""greentechhub-fastapi: the FastAPI/Starlette adapter package for the
GreenTechHub ecosystem.

Unlike greentechhub_core's root __init__.py (a docstring only — that package
imports its modules explicitly), this root re-exports the register_* functions,
matching docs/registration.md's own usage example:
    from greentechhub_fastapi import (
        register_core, register_logging, register_health,
        register_exception_handlers, register_auth,
    )

register_exception_handlers comes from greentechhub_fastapi.exceptions rather
than greentechhub_fastapi.registration — it has no registration/*.py wrapper,
since docs/exceptions.md's own usage example imports it directly from its
module, unlike register_health/register_core/register_logging/register_auth.

PageParams (from greentechhub_fastapi.query), and get_current_user /
get_current_identity / the session-cookie helpers (from
greentechhub_fastapi.auth / greentechhub_fastapi.dependencies), are
deliberately not re-exported here: they're per-route Depends() dependencies
or route-local helpers, not one-time app-level registration calls, and each
module's own doc sample imports them directly from their own module.

register_auth only implements the "local" adapter (docs/auth.md) — selecting
AUTH_ADAPTER="forward_auth" raises NotImplementedError until v0.5, once a real
Authentik instance exists to test against.
"""

from greentechhub_fastapi.exceptions import register_exception_handlers
from greentechhub_fastapi.registration import (
    register_auth,
    register_core,
    register_health,
    register_logging,
)

__all__ = [
    "register_auth",
    "register_core",
    "register_exception_handlers",
    "register_health",
    "register_logging",
]
