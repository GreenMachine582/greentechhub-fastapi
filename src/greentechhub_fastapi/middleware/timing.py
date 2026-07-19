"""TimingMiddleware — adds an X-Response-Time response header (milliseconds, e.g.
"12.34ms") measuring wall-clock time from request start to the first byte of the
response being sent.

Deliberately header-only, not a log line: greentechhub_core.logging.JSONFormatter's
fields are fixed (timestamp/level/logger/message/request_id/exception) with no
extensibility point for arbitrary structured fields yet, so emitting a "request
took Nms" log line here would just be an unstructured message string, which isn't
worth the noise. A future formatter enhancement can add structured timing logs
without touching this middleware.
"""

import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEADER_NAME = "X-Response-Time"


class TimingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()

        async def send_with_timing(message: Message) -> None:
            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter() - start) * 1000
                headers = MutableHeaders(scope=message)
                headers.append(_HEADER_NAME, f"{elapsed_ms:.2f}ms")
            await send(message)

        await self.app(scope, receive, send_with_timing)
