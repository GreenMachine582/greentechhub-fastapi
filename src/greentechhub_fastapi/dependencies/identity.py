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

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request
from greentechhub_core.identity import Identity
from greentechhub_core.types import UnauthorizedError

from greentechhub_fastapi.auth.dependency import get_current_user


async def get_current_identity(user: Identity | None = Depends(get_current_user)) -> Identity:
    if user is None:
        raise UnauthorizedError("authentication required")
    return user


def require_page_identity(login_url: str = "/login") -> Callable[..., Awaitable[Identity]]:
    """Build a "must be logged in" dependency for server-rendered page routes.

    get_current_identity is for JSON APIs (401 envelope). A browser page
    wants a redirect to the login form instead, and an HTMX request needs a
    third answer: its XHR would silently follow a 303 and swap the login page
    into whatever fragment it targeted (a table body, a modal). So:

    - normal request, no identity -> 303 to `login_url`
    - HTMX request (`HX-Request` header), no identity -> 401 with
      `HX-Redirect: login_url`, which HTMX turns into a full-page navigation
      (it honours HX-Redirect on any status)

    Usage: `APIRouter(dependencies=[Depends(require_page_identity())])`, or
    `identity: Identity = Depends(page_identity)` with `page_identity =
    require_page_identity()` built once at module level. `login_url`
    defaults to LoginViews' own default mount path.
    """

    async def dependency(
        request: Request, user: Identity | None = Depends(get_current_user)
    ) -> Identity:
        if user is not None:
            return user
        if request.headers.get("HX-Request"):
            raise HTTPException(status_code=401, headers={"HX-Redirect": login_url})
        raise HTTPException(status_code=303, headers={"Location": login_url})

    return dependency
