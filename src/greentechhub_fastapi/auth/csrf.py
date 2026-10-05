"""csrf — opt-in CSRF protection for the auth views' forms (LoginViews,
RegisterViews, PasswordResetViews, EmailVerificationViews), with the
double-submit cookie pattern.

The sessions here are stateless JWTs, so there's no server-side session to
keep a token in. Instead a form's page sets a random token (core's
generate_token) as the `gth_csrf` cookie and writes the same token into the
form (greentechhub-ui's gth_csrf_field renders `csrf_token` as a hidden
field); the POST must send both, and they must match (core's
constant_time_compare). A page on another site can't read the cookie, so it
can't fill in the field. The token isn't rotated on every page, so the back
button and a second tab keep working.

Like the session cookie, the cookie is httponly, secure and samesite=lax: JS
never needs it, since the server writes the token into the form. Over plain
HTTP (local testing) a secure cookie isn't sent back, so every protected
POST is refused; turn `csrf` off there, as the session cookie already makes
plain HTTP a non-goal.
"""

import string

from fastapi import Request, Response
from greentechhub_core.security import constant_time_compare, generate_token

CSRF_COOKIE_NAME = "gth_csrf"
CSRF_FIELD = "csrf_token"
CSRF_REFUSED = "Your session expired. Please try again."

_STATE = "gth_csrf_token"
_TOKEN_CHARS = frozenset(string.ascii_letters + string.digits + "-_")


def _well_formed(token: str | None) -> bool:
    return bool(token) and 20 <= len(token) <= 128 and set(token) <= _TOKEN_CHARS


def csrf_token_for(request: Request) -> str:
    """The request's CSRF token: its cookie when it holds a well-formed one,
    else a fresh one."""
    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    return cookie if cookie is not None and _well_formed(cookie) else generate_token()


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(CSRF_COOKIE_NAME, token, httponly=True, secure=True, samesite="lax",
                        path="/")


def csrf_ok(request: Request, submitted: str | None) -> bool:
    """Whether the submitted form token matches the cookie; never for an
    empty one."""
    cookie = request.cookies.get(CSRF_COOKIE_NAME) or ""
    return bool(cookie) and bool(submitted) and constant_time_compare(cookie, submitted or "")


class CsrfProtected:
    """The auth views' opt-in CSRF: set `csrf = True` on a subclass. Renders
    then carry `csrf_token` and set the cookie, and each POST is checked
    before anything else, answering 403 when it fails."""

    #: Check a CSRF token on every POST (opt-in). Needs greentechhub-ui v0.15+
    #: (or a template with the hidden `csrf_token` field).
    csrf: bool = False

    def _csrf_context(self, request: Request) -> dict[str, str]:
        if not self.csrf:
            return {}
        token = getattr(request.state, _STATE, None) or csrf_token_for(request)
        setattr(request.state, _STATE, token)
        return {CSRF_FIELD: token}

    def _with_csrf_cookie(self, request: Request, response: Response) -> Response:
        token = getattr(request.state, _STATE, None)
        if self.csrf and token:
            set_csrf_cookie(response, token)
        return response

    def _csrf_refused(self, request: Request, submitted: str | None) -> bool:
        return self.csrf and not csrf_ok(request, submitted)
