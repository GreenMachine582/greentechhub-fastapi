"""flash — signed-cookie flash messages: flash(response, message, kind) queues
one, Depends(get_flashes) reads and clears them on the next render.

No server-side session: state lives entirely in one `gth_flash` cookie holding
a JSON list of `{message, kind}` pairs, signed with `itsdangerous.
URLSafeSerializer` so a tampered cookie is detected and discarded rather than
trusted. Same security posture as auth/cookies.py's session cookie
(httponly/secure/samesite=lax/path=/) — flash values aren't secret, but there
is no reason to relax the one cookie policy this package already has.

The serializer needs `settings.secret_key`, which flash()/get_flashes() don't
take as a parameter (matching the brief's call-site-ergonomic signature:
`flash(response, "Saved!", kind="success")` inline in a route handler, no
settings object at hand). So `registration.flash.register_flash(app,
settings)` configures a module-level serializer once at startup — the same
"configure once, read many times" shape `greentechhub_core.events.subscribe`'s
`default_event_bus` singleton already uses — and this module's functions read
it from here.

Two-path rule (see docs/modules.md "Flash and events"): a full-page render
uses flash()/get_flashes(); an HTMX partial response should prefer
`greentechhub_ui.toast()`'s `HX-Trigger` header instead, since the flash
cookie is only consumed on the *next* full render, not the current partial.
"""

from greentechhub_core.types import FlashMessage
from itsdangerous import BadData, URLSafeSerializer
from starlette.requests import Request
from starlette.responses import Response

FLASH_COOKIE_NAME = "gth_flash"
_PENDING_ATTR = "_gth_pending_flashes"

_serializer: URLSafeSerializer | None = None


def _configure(secret_key: str) -> None:
    """Set the module-level serializer. Called by registration.flash.register_flash —
    not part of this module's public surface.
    """
    global _serializer
    _serializer = URLSafeSerializer(secret_key, salt="gth-flash")


def _require_serializer() -> URLSafeSerializer:
    if _serializer is None:
        raise RuntimeError(
            "flash()/get_flashes() used before register_flash(app, settings) ran."
        )
    return _serializer


def _set_flash_cookie(response: Response, payload: list[dict[str, str]]) -> None:
    token = _require_serializer().dumps(payload)
    response.set_cookie(
        FLASH_COOKIE_NAME, token, httponly=True, secure=True, samesite="lax", path="/"
    )


def flash(response: Response, message: str, kind: str = "success") -> None:
    """Queue one flash message onto `response`'s `gth_flash` cookie.

    Reads back any pending flashes this same `response` object already
    queued (via a private attribute, `_gth_pending_flashes`) so multiple
    flash() calls in one handler before a redirect all survive — the cookie
    only ever gets one `Set-Cookie` write per call, but that write always
    carries the *cumulative* list, not just this message.
    """
    pending: list[dict[str, str]] = getattr(response, _PENDING_ATTR, [])
    pending = [*pending, {"message": message, "kind": kind}]
    setattr(response, _PENDING_ATTR, pending)
    _set_flash_cookie(response, pending)


def get_flashes(request: Request, response: Response) -> list[FlashMessage]:
    """`Depends`-ready: read and clear the `gth_flash` cookie.

    FastAPI injects `Request`/`Response` directly for a dependency
    parameter typed as either, so this needs no `Depends(...)` wrapper of
    its own at the call site (`Depends(get_flashes)` is enough).

    Always clears the cookie, even when it's missing/tampered, so a stale
    or corrupt cookie doesn't linger. Returns `[]` rather than raising on a
    missing cookie or any `BadData` (bad signature, corrupt payload) — a
    flash cookie is optional, best-effort state, never something a render
    should fail over.
    """
    response.delete_cookie(FLASH_COOKIE_NAME, httponly=True, secure=True, samesite="lax", path="/")

    raw = request.cookies.get(FLASH_COOKIE_NAME)
    if not raw:
        return []

    try:
        items = _require_serializer().loads(raw)
    except BadData:
        return []

    return [FlashMessage(message=item["message"], kind=item["kind"]) for item in items]


def flash_context(flashes: list[FlashMessage]) -> dict[str, list[dict[str, str]]]:
    """Build the `ui` context-contract shape (`{"flashes": [...]}`) from an
    already-resolved flash list.

    Deliberately takes `flashes`, not `request` — a route handler already
    has the list via `Depends(get_flashes)` (which is also what clears the
    cookie); re-deriving it from `request` here would need its own
    `Response` to clear the cookie too, doubling that logic for no benefit.
    """
    return {"flashes": [{"message": item.message, "kind": item.kind} for item in flashes]}
