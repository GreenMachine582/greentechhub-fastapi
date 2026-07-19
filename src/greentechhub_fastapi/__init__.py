"""greentechhub-fastapi: the FastAPI/Starlette adapter package for the
GreenTechHub ecosystem.

Unlike greentechhub_core's root __init__.py (a docstring only — that package
imports its modules explicitly), this root re-exports the register_* functions,
matching docs/registration.md's own usage example:
    from greentechhub_fastapi import register_core, register_logging, register_health

register_auth is intentionally not re-exported (or implemented) yet — it's gated
on greentechhub-core's identity/permissions modules landing (v0.3), not on
anything in this v0.1 slice.
"""

from greentechhub_fastapi.registration import register_core, register_health, register_logging

__all__ = ["register_core", "register_health", "register_logging"]
