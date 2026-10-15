"""CspMiddleware — a per-request nonce and a Content-Security-Policy header,
for greentechhub-ui's CSP-ready app shell (register_csp installs it).

Each HTTP request gets a fresh nonce on `request.state.csp_nonce`, which
ui_context passes to templates as `csp_nonce`; app.html puts it on every
<script> it renders. The response then carries the policy with that nonce,
unless the route already set its own Content-Security-Policy.

DEFAULT_CSP is greentechhub-ui's recommended policy (its docs/contract.md ›
Content-Security-Policy): scripts only from 'self' or with the nonce, no
'unsafe-inline' or 'unsafe-eval' for scripts, so templates mustn't use the
htmx features that eval (hx-on, hx-vars, js: in hx-vals, hx-trigger filters).
"""

from collections.abc import Iterable

from greentechhub_core.security import generate_token
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP_STATE = "csp_nonce"

_DEFAULT_DIRECTIVES = {
    "default-src": "'self'",
    "script-src": "'self' 'nonce-{nonce}'",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": "'self' data:",
    "font-src": "'self'",
    "connect-src": "'self'",
    "frame-src": "'self'",
    "frame-ancestors": "'self'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "object-src": "'none'",
}

DEFAULT_CSP = "; ".join(f"{name} {value}" for name, value in _DEFAULT_DIRECTIVES.items())
"""greentechhub-ui's recommended policy, with `{nonce}` where the nonce goes."""


def content_security_policy(
    *, frame_src: Iterable[str] = (), connect_src: Iterable[str] = ()
) -> str:
    """DEFAULT_CSP with extra sources added to frame-src (e.g. the Grafana
    origin behind a gth_embed_card) and connect-src. `{nonce}` stays in it."""
    directives = dict(_DEFAULT_DIRECTIVES)
    for name, extra in (("frame-src", frame_src), ("connect-src", connect_src)):
        sources = " ".join(extra)
        if sources:
            directives[name] = f"{directives[name]} {sources}"
    return "; ".join(f"{name} {value}" for name, value in directives.items())


class CspMiddleware:
    """Puts a fresh nonce on request.state.csp_nonce and sends `policy` with
    it as the Content-Security-Policy header, unless the response already has
    one.

    Args:
        policy: the header value, with `{nonce}` where the nonce goes
            (default DEFAULT_CSP).
    """

    def __init__(self, app: ASGIApp, policy: str = DEFAULT_CSP) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        nonce = generate_token(num_bytes=16)
        scope.setdefault("state", {})[CSP_STATE] = nonce
        header = self.policy.format(nonce=nonce)

        async def send_with_csp(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "content-security-policy" not in headers:
                    headers.append("Content-Security-Policy", header)
            await send(message)

        await self.app(scope, receive, send_with_csp)
