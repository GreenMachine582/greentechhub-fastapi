"""register_events — wires startup/shutdown Event publishing into the FastAPI
app lifecycle.

Decided 2026-09 (see TODO.md v0.4): (a) with a narrow (b). `EventBus`/
`publish()` are process-global singletons needing no setup/teardown today, so
a lifespan hook has nothing to open or close *yet* — but the eventual Redis
event backend will need a connection opened at startup and closed at
shutdown, and that hook must exist *before* services are written, or every
service changes when Redis lands. This installs that hook now; its only job
today is publishing caller-supplied startup/shutdown events (useful on its
own for a `ServiceStarted`-style audit line), and it becomes the Redis
backend's connect/disconnect point later without any call-site changing.

No lifespan mechanism exists anywhere else in this package yet, and FastAPI/
Starlette supports exactly one `lifespan` callable per app (set via
`app.router.lifespan_context`, defaulting to a no-op async context manager).
So this can't just assign a fresh lifespan — it must wrap whatever is already
there, so register_events composes with any lifespan a service (or a future
registration function) already installed, in either registration order.
"""

from collections.abc import Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from greentechhub_core.events import Event, publish


def register_events(
    app: FastAPI,
    *,
    on_startup: Sequence[Event] = (),
    on_shutdown: Sequence[Event] = (),
) -> None:
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        async with previous_lifespan(app) as state:
            for event in on_startup:
                await publish(event)
            try:
                yield state
            finally:
                for event in on_shutdown:
                    await publish(event)

    app.router.lifespan_context = _lifespan
