"""get_current_identity — the "must be authenticated" counterpart to
get_current_user.

get_current_user (auth/dependency.py) deliberately allows anonymous access,
resolving to None when no valid session exists — appropriate for a route that
behaves differently for logged-in vs. anonymous callers. A route that
requires authentication shouldn't have to repeat the same
"if user is None: raise ..." check itself; this dependency does it once.

Raises UnauthorizedError rather than returning None or raising an FastAPI
HTTPException directly: it composes with the already-shipped exceptions
module (greentechhub_fastapi.exceptions.register_exception_handlers maps
UnauthorizedError to a 401 JSON envelope), keeping every "the caller isn't
who/what we need them to be" response in this ecosystem shaped the same way
regardless of which layer raised it.

Feature-flag lookups and permission/RBAC checks (has_permission) are
deliberately not wrapped here or anywhere else in this module — no doc on
either package's roadmap calls for a fastapi-side dependency for them yet;
adding one now would be scope creep beyond what this task asked for.
"""

from fastapi import Depends
from greentechhub_core.identity import Identity
from greentechhub_core.types import UnauthorizedError

from greentechhub_fastapi.auth.dependency import get_current_user


async def get_current_identity(user: Identity | None = Depends(get_current_user)) -> Identity:
    if user is None:
        raise UnauthorizedError("authentication required")
    return user
