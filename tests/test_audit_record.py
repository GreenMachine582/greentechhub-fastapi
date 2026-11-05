"""record_audit (audit() with no request) and an activity page on
AuditViews(permission=None)."""

import asyncio

import httpx
from fastapi import Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.audit import InMemoryAuditStore
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi import register_audit
from greentechhub_fastapi.audit import AuditViews, audit, record_audit
from tests.conftest import build_app


def test_an_activity_page_from_audit_and_record_audit(settings, tmp_path):
    (tmp_path / "audit_page.html").write_text(
        "{% for e in audit_entries %}ROW {{ e.action }} {{ e.actor }}\n{% endfor %}",
        encoding="utf-8")
    store = InMemoryAuditStore()
    app = build_app(settings)
    register_audit(app, settings, store=store,
                   views=AuditViews(templates=Jinja2Templates(directory=tmp_path),
                                    permission=None))

    @app.post("/plans/apply")
    async def apply(request: Request):
        await audit(request, "plan.applied", target=("plan", "7"), summary="Applied 12 moves")
        return {"ok": True}

    async def main():
        await record_audit(app, "scan.finished", summary="Scanned 120 files")
        provider = DevelopmentIdentityProvider(secret_key="test-secret")
        cookies = {"gth_session": provider.issue(
            Identity(subject="sam", username="sam", email=None, groups=[], claims={}))}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test", cookies=cookies) as client:
            await client.post("/plans/apply")
            return await client.get("/admin/audit")

    page = asyncio.run(main())
    assert page.status_code == 200
    assert page.text.splitlines() == ["ROW plan.applied sam", "ROW scan.finished None"]


def test_record_audit_takes_an_actor_and_is_a_no_op_unregistered(settings):
    app = build_app(settings)
    assert asyncio.run(record_audit(app, "scan.finished")) is None
    store = InMemoryAuditStore()
    register_audit(app, settings, store=store)
    entry = asyncio.run(record_audit(app, "scan.finished", actor="alice",
                                     details={"files": 3, "password": "x"}))
    assert entry is not None and entry.actor == "alice"
    assert store.entries_sync()[0].details["files"] == 3
    assert store.entries_sync()[0].details.get("password") != "x"


def test_record_audit_logs_a_failing_store(settings, caplog):
    class _Broken(InMemoryAuditStore):
        async def record(self, entry):
            raise RuntimeError("disk full")

    app = build_app(settings)
    register_audit(app, settings, store=_Broken())
    assert asyncio.run(record_audit(app, "scan.finished")) is None
    assert "recording scan.finished failed" in caplog.text
