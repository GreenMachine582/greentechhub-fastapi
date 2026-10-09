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

Beyond the auth forms (opt-in, v0.16): register_csrf installs CsrfMiddleware,
which gives every request the same token (reusing a well-formed cookie, else
minting one and setting the cookie on the response), and templating's
ui_context passes it to templates as `csrf_token`. greentechhub-ui's app
shell then sends it on every htmx request as the X-CSRF-Token header and as
a hidden field on the navbar's logout form. require_csrf checks either on a
state-changing route; SettingsViews(csrf=True), RoleAdminViews(csrf=True)
and LoginViews.logout_csrf opt this package's own routes in.
"""

import string
from collections.abc import Mapping
from http.cookies import SimpleCookie
from typing import Any

from fastapi import HTTPException, Request, Response
from greentechhub_core.security import constant_time_compare, generate_token
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSRF_COOKIE_NAME = "gth_csrf"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_REFUSED = "Your session expired. Please try again."

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

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


def request_csrf_token(request: Request) -> str | None:
    """The token CsrfMiddleware gave this request, or None without it."""
    return getattr(request.state, _STATE, None)


async def require_csrf(request: Request) -> None:
    """A dependency for a state-changing route: a GET/HEAD/OPTIONS passes, any
    other method needs the gth_csrf cookie's token back, as the X-CSRF-Token
    header (htmx, through the app shell's hx-headers) or the csrf_token form
    field (a plain form), else 403 with CSRF_REFUSED."""
    if request.method in SAFE_METHODS:
        return
    submitted = request.headers.get(CSRF_HEADER)
    if not submitted and request.headers.get("content-type", "").startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        submitted = str((await request.form()).get(CSRF_FIELD) or "")
    if not csrf_ok(request, submitted):
        raise HTTPException(status_code=403, detail=CSRF_REFUSED)


class CsrfMiddleware:
    """Gives every HTTP request a CSRF token (register_csrf installs it): the
    request's well-formed gth_csrf cookie, else a fresh token, which is then
    set as the cookie on the response. The token sits on request.state, where
    request_csrf_token, ui_context and the auth views' forms all find it, so
    a page and its forms always agree. Checks nothing itself: that's
    require_csrf."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cookie = HTTPConnection(scope).cookies.get(CSRF_COOKIE_NAME)
        fresh = cookie is None or not _well_formed(cookie)
        token = generate_token() if fresh else cookie
        scope.setdefault("state", {})[_STATE] = token

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start" and fresh:
                headers = MutableHeaders(scope=message)
                if not _sets_csrf_cookie(headers):
                    morsel = SimpleCookie()
                    morsel[CSRF_COOKIE_NAME] = token
                    morsel[CSRF_COOKIE_NAME].update(
                        {"httponly": True, "secure": True, "samesite": "lax", "path": "/"})
                    headers.append("set-cookie", morsel.output(header="").strip())
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def _sets_csrf_cookie(headers: MutableHeaders) -> bool:
    # An auth view's form already set it (with the same token).
    return any(value.startswith(f"{CSRF_COOKIE_NAME}=") for value in headers.getlist("set-cookie"))


class CsrfProtected:
    """The auth views' opt-in CSRF: set `csrf = True` on a subclass. Renders
    then carry `csrf_token` and set the cookie, and each POST is checked
    before anything else, answering 403 when it fails."""

    #: Check a CSRF token on every POST (opt-in). Needs greentechhub-ui v0.15+
    #: (or a template with the hidden `csrf_token` field).
    csrf: bool = False

    #: The Jinja2Templates a view renders with (set by each view's __init__).
    _templates: Any

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

    def _render_form(
        self,
        request: Request,
        template: str,
        context: Mapping[str, Any],
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """`template` with `context` plus the CSRF token, and the CSRF cookie
        set: how every one of these views renders a form page."""
        response = self._templates.TemplateResponse(
            request, template, {**self._csrf_context(request), **context},
            status_code=status_code, headers=headers,
        )
        return self._with_csrf_cookie(request, response)
