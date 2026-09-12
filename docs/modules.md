[← Back to README](../README.md)

# 🧩 Middleware, Flash, Events, Dependencies

The smaller modules that don't warrant their own doc yet — see [docs/registration.md](registration.md), [docs/auth.md](auth.md), [docs/query.md](query.md), [docs/health.md](health.md), and [docs/exceptions.md](exceptions.md) for the higher-detail ones.

## Middleware

Wired via `register_core(app, settings)`, see [docs/registration.md](registration.md).

## Flash and events

### Flash

`flash.py` — signed-cookie flash, no server-side session. `register_flash(app, settings)` configures
the cookie serializer once, from `settings.secret_key`; then any route can call:

```python
from greentechhub_fastapi.flash import flash, get_flashes, flash_context

@app.post("/save")
async def save(response: Response):
    flash(response, "Saved!", kind="success")
    return RedirectResponse("/", status_code=303)

@app.get("/")
async def index(flashes: list[FlashMessage] = Depends(get_flashes)):
    return templates.TemplateResponse("index.html", {**flash_context(flashes), ...})
```

`flash(response, message, kind="success")` queues one message onto the `gth_flash` cookie — calling it
more than once in the same handler accumulates, it doesn't overwrite. `get_flashes(request, response)`
(a `Depends`-ready function) reads and clears that cookie, returning `[]` on a missing or tampered
value, never raising. `flash_context(flashes)` shapes an already-resolved list into
`{"flashes": [...]}` for the `greentechhub-ui` context contract.

**Two-path rule:** a full-page render uses `flash()`/`get_flashes()` — the message survives the
redirect via the cookie, consumed on the next render. An HTMX partial response should use
`greentechhub_ui.toast()`'s `HX-Trigger` header instead, since the flash cookie is only read on the
*next full render*, not the current partial swap.

### Events

`events.py` — `get_event_publisher()` is a `Depends`-ready function returning `greentechhub_core.
events.publish` directly (not a new wrapper class), so a route depends on it via
`Depends(get_event_publisher)` and a test can override it with a recording fake via
`app.dependency_overrides`.

`registration/events.py` — `register_events(app, *, on_startup: Sequence[Event] = (), on_shutdown:
Sequence[Event] = ())` installs a FastAPI lifespan hook publishing the given events on
startup/shutdown. Decided 2026-09: `Depends(get_event_publisher)` for route-time publishing, plus this
narrow lifespan hook — not because today's `EventBus`/`publish()` need any setup/teardown of their own
(they don't), but because the lifespan hook has to exist *before* services are written if it's going to
be the future home of the Redis event backend's connect/disconnect; adding it later would mean every
service's registration call changes. `register_events` wraps whatever lifespan `app` already has
(FastAPI/Starlette only supports one), rather than replacing it, so it composes regardless of
registration order.

## Dependencies

Small `Depends`-ready helpers beyond auth (current identity, feature-flag lookups, pagination params) — grows only when a real service needs a new helper, not scoped up front, matching `greentechhub-core`'s own bias against dumping-ground modules.
