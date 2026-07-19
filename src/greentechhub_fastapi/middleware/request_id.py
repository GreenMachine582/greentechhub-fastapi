"""RequestIDMiddleware — assigns/propagates a per-request ID via
greentechhub_core.logging's contextvar, so every log line emitted while handling a
request carries it automatically (see JSONFormatter), and echoes it back to the
caller for cross-service correlation.

Pure ASGI rather than BaseHTTPMiddleware: this needs to run set_request_id before
anything downstream executes and reset_request_id after everything downstream
(including background tasks scheduled during the request) has finished sending —
a plain ASGI middleware wrapping receive/send gives that without the buffering
BaseHTTPMiddleware imposes on streamed responses.
"""

import uuid

from greentechhub_core.logging import reset_request_id, set_request_id
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEADER_NAME = "X-Request-ID"


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp, *, header_name: str = _HEADER_NAME) -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _get_header(scope, self.header_name)
        request_id = incoming or str(uuid.uuid4())
        token = set_request_id(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(self.header_name, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            reset_request_id(token)


def _get_header(scope: Scope, name: str) -> str | None:
    lowered = name.lower().encode("latin-1")
    for key, value in scope["headers"]:
        if key.lower() == lowered:
            return value.decode("latin-1")
    return None
