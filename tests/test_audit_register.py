"""register_audit and the audit() helper: nothing is recorded until the store
is registered, the signed-in user is the default actor, an explicit actor
(or None for the system) wins, and a failing store is logged, not raised."""

import asyncio
import logging

import httpx
import pytest
from fastapi import FastAPI, Request
from greentechhub_core.audit import InMemoryAuditStore
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi import register_audit
from greentechhub_fastapi.audit import audit, get_audit_store
from tests.conftest import build_app


def _app(settings, store=None) -> FastAPI:
    app = build_app(settings)
    if store is not None:
        register_audit(app, settings, store=store)

    @app.post("/do")
    async def do(request: Request):
        entry = await audit(request, "stock.archived", target=("stock", 42),
                            summary="Archived ASX:BHP", details={"api_key": "abc", "n": 1})
        return {"recorded": entry is not None}

    @app.post("/system")
    async def system(request: Request):
        await audit(request, "sync.finished", actor=None)
        return {}

    return app


def _post(app, path, subject=None):
    async def go():
        cookies = None
        if subject:
            provider = DevelopmentIdentityProvider(secret_key="test-secret")
            cookies = {"gth_session": provider.issue(
                Identity(subject=subject, username=subject, email=None, groups=[], claims={}))}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     cookies=cookies) as client:
            return await client.post(path)

    return asyncio.run(go())


def test_nothing_is_recorded_until_registered(settings):
    response = _post(_app(settings), "/do", subject="alice")
    assert response.json() == {"recorded": False}


def test_the_signed_in_user_is_the_actor_and_details_are_scrubbed(settings):
    store = InMemoryAuditStore()
    assert _post(_app(settings, store), "/do", subject="alice").json() == {"recorded": True}
    (entry,) = store.entries_sync()
    assert (entry.actor, entry.action, entry.target_type, entry.target_id, entry.summary) == (
        "alice", "stock.archived", "stock", "42", "Archived ASX:BHP")
    assert entry.details["n"] == 1 and entry.details["api_key"] != "abc"


def test_anonymous_and_system_entries_have_no_actor(settings):
    store = InMemoryAuditStore()
    app = _app(settings, store)
    _post(app, "/do")
    _post(app, "/system", subject="alice")
    assert [(e.action, e.actor) for e in store.entries_sync()] == [
        ("sync.finished", None), ("stock.archived", None)]


def test_a_failing_store_is_logged_not_raised(settings, caplog):
    class Broken(InMemoryAuditStore):
        async def record(self, entry):
            raise OSError("database is down")

    with caplog.at_level(logging.ERROR, logger="greentechhub_fastapi.audit"):
        response = _post(_app(settings, Broken()), "/do", subject="alice")
    assert response.status_code == 200 and response.json() == {"recorded": False}
    assert "recording stock.archived failed" in caplog.text


def test_register_audit_returns_the_store_and_exposes_it(settings):
    app = FastAPI()
    store = InMemoryAuditStore()
    assert register_audit(app, settings, store=store) is store

    @app.get("/store")
    async def which(request: Request):
        return {"same": get_audit_store(request) is store}

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/store")

    assert asyncio.run(go()).json() == {"same": True}


def test_register_audit_after_start_is_refused(settings):
    app = FastAPI()
    app.middleware_stack = app.build_middleware_stack()
    with pytest.raises(RuntimeError, match="before the app starts"):
        register_audit(app, settings, store=InMemoryAuditStore())
