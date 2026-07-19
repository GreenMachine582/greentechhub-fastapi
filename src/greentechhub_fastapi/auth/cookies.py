"""cookies — the session cookie every local-auth login/logout route sets/clears.

SESSION_COOKIE_NAME is a hardcoded literal, not a Settings field — same
precedent as X-Request-ID being a hardcoded header name in
middleware/request_id.py, not something this package makes configurable.

The cookie flags (httponly, secure, samesite, path) are similarly fixed, not
exposed as settings, matching SecurityHeadersMiddleware's "small, fixed, safe
by default" policy rather than a configurable framework:
  - httponly=True: never readable from JS, so an XSS bug can't steal the
    session token directly.
  - secure=True: never sent over plain HTTP. A service testing locally over
    plain HTTP won't see the cookie round-trip — a known, accepted
    limitation of defaulting to the safe posture, not a bug to work around
    by inventing a new setting.
  - samesite="lax": a reasonable CSRF baseline for a session cookie without
    breaking top-level navigation (e.g. following a link into the app).
  - path="/": the cookie applies to the whole app, not just the route that
    set it.

Login/logout routes themselves are NOT provided by this package (see
docs/auth.md: they "call a service's own credential-check logic... and then
use this module purely to set/clear the session cookie") — only these two
helper functions are.
"""

from fastapi import Response

SESSION_COOKIE_NAME = "gth_session"


def create_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
