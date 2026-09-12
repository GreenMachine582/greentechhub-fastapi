import dataclasses
from contextlib import asynccontextmanager

import pytest
from fastapi import Depends, FastAPI
from greentechhub_core.events import Event, default_event_bus, publish, subscribe
from starlette.testclient import TestClient

from greentechhub_fastapi import register_core, register_health
from greentechhub_fastapi.events import get_event_publisher
from greentechhub_fastapi.registration.events import register_events


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _ServiceStarted(Event):
    pass


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _ServiceStopped(Event):
    pass


@pytest.fixture(autouse=True)
def _clear_default_event_bus():
    default_event_bus.clear()
    yield
    default_event_bus.clear()


def test_register_events_publishes_startup_events_exactly_once():
    received = []
    subscribe(_ServiceStarted, received.append)
    app = FastAPI()
    register_events(app, on_startup=[_ServiceStarted()])

    with TestClient(app):
        pass

    assert len(received) == 1


def test_register_events_publishes_shutdown_events_on_exit_not_before():
    received = []
    subscribe(_ServiceStopped, received.append)
    app = FastAPI()
    register_events(app, on_shutdown=[_ServiceStopped()])

    with TestClient(app):
        assert received == []

    assert len(received) == 1


def test_register_events_composes_with_an_existing_lifespan():
    calls = []

    @asynccontextmanager
    async def _existing_lifespan(app: FastAPI):
        calls.append("start")
        yield
        calls.append("stop")

    app = FastAPI(lifespan=_existing_lifespan)
    register_events(app, on_startup=[_ServiceStarted()])
    received = []
    subscribe(_ServiceStarted, received.append)

    with TestClient(app):
        pass

    assert calls == ["start", "stop"]
    assert len(received) == 1


def test_register_events_composes_with_register_core_and_register_health(settings):
    app = FastAPI()
    register_core(app, settings)
    register_health(app)
    register_events(app, on_startup=[_ServiceStarted()])
    received = []
    subscribe(_ServiceStarted, received.append)

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert len(received) == 1


def test_get_event_publisher_returns_the_core_publish_callable():
    assert get_event_publisher() is publish


def test_get_event_publisher_dependency_can_be_overridden_in_tests():
    app = FastAPI()
    recorded = []

    async def _fake_publish(event: Event) -> None:
        recorded.append(event)

    app.dependency_overrides[get_event_publisher] = lambda: _fake_publish

    @app.post("/do-thing")
    async def do_thing(publish_event=Depends(get_event_publisher)):
        await publish_event(_ServiceStarted())
        return {"ok": True}

    with TestClient(app) as client:
        response = client.post("/do-thing")
        assert response.status_code == 200

    assert len(recorded) == 1
