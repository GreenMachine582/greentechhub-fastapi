"""greentechhub-fastapi: the FastAPI/Starlette adapter package for the
GreenTechHub ecosystem.

Unlike greentechhub_core's root __init__.py (a docstring only — that package
imports its modules explicitly), this root re-exports the register_* functions,
matching docs/registration.md's own usage example:
    from greentechhub_fastapi import (
        register_core, register_logging, register_health, register_exception_handlers,
    )

register_exception_handlers comes from greentechhub_fastapi.exceptions rather
than greentechhub_fastapi.registration — it has no registration/*.py wrapper,
since docs/exceptions.md's own usage example imports it directly from its
module, unlike register_health/register_core/register_logging.

PageParams (from greentechhub_fastapi.query) is deliberately not re-exported
here: it's a per-route Depends() dependency, not a one-time app-level
registration call, and docs/query.md's own usage example imports it from
greentechhub_fastapi.query directly.

register_auth is intentionally not re-exported (or implemented) yet — it's gated
on greentechhub-core's identity/permissions modules landing (v0.3), not on
anything in this v0.2 slice.
"""

from greentechhub_fastapi.exceptions import register_exception_handlers
from greentechhub_fastapi.registration import register_core, register_health, register_logging

__all__ = [
    "register_core",
    "register_exception_handlers",
    "register_health",
    "register_logging",
]
