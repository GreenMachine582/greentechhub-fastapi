"""SecurityHeadersMiddleware — a small, fixed set of defensive response headers
applied to every response, deliberately minimal (per this package's own "safe by
default, one line to extend" philosophy — see docs/registration.md) rather than a
configurable security-headers framework:

  - X-Content-Type-Options: nosniff
      Stops browsers guessing content-type from body contents — prevents a response
      served as e.g. text/plain being executed as script/HTML.
  - X-Frame-Options: DENY
      Stops this service's pages being framed by another origin (clickjacking).
      Blunt (no same-origin allowance) since these are API-first services; a
      service that actually needs framing can strip/replace it downstream.
  - Referrer-Policy: strict-origin-when-cross-origin
      Browsers' current sane default — full URL sent same-origin, origin-only
      cross-origin, nothing over a scheme downgrade (https->http).

Deliberately NOT included: Strict-Transport-Security (this middleware runs
before/independent of TLS-termination awareness — see ProxyHeadersMiddleware; an
HSTS header on a response that might legitimately be served over plain HTTP behind
a non-TLS-terminating proxy would be actively harmful), and Content-Security-Policy
(inherently service-specific, no safe universal default exists).
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _HEADERS.items():
                    headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
