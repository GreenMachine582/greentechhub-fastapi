"""AuditViews: the audit log page, gated like RoleAdminViews, newest first,
filtered by actor, action (exact or a "prefix.") and an on-or-before date,
paged back with a `before` cursor that keeps the filters."""

import asyncio
from datetime import UTC, datetime, timedelta
from html import unescape
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.templating import Jinja2Templates
from greentechhub_core.audit import InMemoryAuditStore, new_entry
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.permissions import Permission, Role

from greentechhub_fastapi import register_audit, register_permissions
from greentechhub_fastapi.audit import AuditViews
from tests.conftest import build_app
from tests.test_role_admin import _Settings

VIEW = Permission("audit.view")
ROLES = (Role(name="auditor", permissions={VIEW}), Role(name="viewer", permissions=set()))
START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

# A stand-in for greentechhub-ui's audit_page.html: it prints the data.
PAGE = """PAGE {{ page_title }} at {{ audit_url }}
FILTERS {{ audit_filters.actor }}|{{ audit_filters.action }}|{{ audit_filters.on_or_before }}
{% for e in audit_entries %}ROW {{ e.action }} {{ e.actor }} {{ e.target }} {{ e.at.isoformat() }}
{% endfor %}NEXT {{ audit_next_url or "-" }}"""


@pytest.fixture
def audit_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ROLE_BOOTSTRAP", "root=auditor,bob=viewer")
    return _Settings()


@pytest.fixture
def store():
    store = InMemoryAuditStore()
    for i, (action, actor) in enumerate([
        ("auth.signed_in", "alice"), ("roles.granted", "root"), ("auth.signed_in", "bob"),
        ("settings.changed", "alice"), ("auth.sign_in_failed", None),
    ]):
        store.record_sync(new_entry(action, actor=actor, target=("user", actor or "x"),
                                    now=START + timedelta(days=i)))
    return store


def _app(settings, store, tmp_path, page_size=50):
    (tmp_path / "audit_page.html").write_text(PAGE, encoding="utf-8")
    views = AuditViews(templates=Jinja2Templates(directory=tmp_path), permission="audit.view")
    views.page_size = page_size
    app = build_app(settings)
    register_permissions(app, settings, roles=ROLES)
    register_audit(app, settings, store=store, views=views)
    return app


def _get(app, path, subject=None):
    async def go():
        cookies = None
        if subject:
            provider = DevelopmentIdentityProvider(secret_key="test-secret")
            cookies = {"gth_session": provider.issue(
                Identity(subject=subject, username=subject, email=None, groups=[], claims={}))}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     cookies=cookies) as client:
            return await client.get(path, headers={"Accept": "text/html"},
                                    follow_redirects=False)

    return asyncio.run(go())


def _rows(response):
    return [line.split()[1:3] for line in response.text.splitlines() if line.startswith("ROW")]


def test_gated_on_the_permission(audit_settings, store, tmp_path):
    app = _app(audit_settings, store, tmp_path)
    assert _get(app, "/admin/audit").status_code == 303  # anonymous → sign in
    assert _get(app, "/admin/audit", subject="bob").status_code == 403
    assert _get(app, "/admin/audit", subject="root").status_code == 200


def test_newest_first(audit_settings, store, tmp_path):
    page = _get(_app(audit_settings, store, tmp_path), "/admin/audit", subject="root")
    assert "PAGE Audit log at /admin/audit" in page.text
    assert _rows(page) == [["auth.sign_in_failed", "None"], ["settings.changed", "alice"],
                           ["auth.signed_in", "bob"], ["roles.granted", "root"],
                           ["auth.signed_in", "alice"]]
    assert "NEXT -" in page.text


def test_filters_by_actor_action_prefix_and_date(audit_settings, store, tmp_path):
    app = _app(audit_settings, store, tmp_path)
    assert _rows(_get(app, "/admin/audit?actor=alice", subject="root")) == [
        ["settings.changed", "alice"], ["auth.signed_in", "alice"]]
    assert [r[0] for r in _rows(_get(app, "/admin/audit?action=auth.", subject="root"))] == [
        "auth.sign_in_failed", "auth.signed_in", "auth.signed_in"]
    on_day_three = _get(app, "/admin/audit?on_or_before=2026-10-03", subject="root")
    assert [r[0] for r in _rows(on_day_three)] == [
        "auth.signed_in", "roles.granted", "auth.signed_in"]
    assert "FILTERS ||2026-10-03" in on_day_three.text


def test_pages_back_keeping_the_filters(audit_settings, store, tmp_path):
    app = _app(audit_settings, store, tmp_path, page_size=2)
    first = _get(app, "/admin/audit?action=auth.", subject="root")
    assert [r[0] for r in _rows(first)] == ["auth.sign_in_failed", "auth.signed_in"]
    next_url = unescape(first.text.rsplit("NEXT ", 1)[1].strip())  # autoescaped, as in an href
    assert parse_qs(urlsplit(next_url).query)["action"] == ["auth."]
    second = _get(app, next_url, subject="root")
    assert _rows(second) == [["auth.signed_in", "alice"]] and "NEXT -" in second.text


def test_unreadable_dates_and_cursors_are_ignored(audit_settings, store, tmp_path):
    app = _app(audit_settings, store, tmp_path)
    page = _get(app, "/admin/audit?on_or_before=soon&before=yesterday", subject="root")
    assert page.status_code == 200 and len(_rows(page)) == 5
