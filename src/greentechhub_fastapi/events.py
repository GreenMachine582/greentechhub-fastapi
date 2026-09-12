"""events — get_event_publisher: the route-local Depends counterpart to
registration.events.register_events.

Returns the plain `publish` callable rather than wrapping it in a new class —
greentechhub_core.events.EventBus/publish are already the right shape (see
core's docs/events.md), and a route handler depending on `Depends(
get_event_publisher)` gets exactly that callable, so a test can swap it for a
recording fake via `app.dependency_overrides[get_event_publisher] = lambda:
fake_publish` without this package inventing its own publisher protocol.
"""

from collections.abc import Awaitable, Callable

from greentechhub_core.events import Event, publish


def get_event_publisher() -> Callable[[Event], Awaitable[None]]:
    return publish
