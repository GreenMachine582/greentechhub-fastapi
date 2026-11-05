"""AUTH_ADAPTER=single_user: every request is one fixed local identity, so
page routes, notifications and notify(app, None, ...) work with no sign-in."""

import asyncio
import logging

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.templating import Jinja2Templates
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.identity import Identity
from greentechhub_core.notifications import InMemoryNotificationStore

from greentechhub_fastapi import register_auth, register_notifications
from greentechhub_fastapi.auth import single_user_identity
from greentechhub_fastapi.dependencies.identity import require_page_identity
from greentechhub_fastapi.notifications import NOTIFICATIONS_EVENT, NotificationViews, notify
from greentechhub_fastapi.testing import hx_triggers
from tests.conftest import build_app


class _SingleUserSettings(GTHBaseSettings):
    CORS_ALLOWED_ORIGINS: str = ""
    TRUSTED_PROXIES: str = ""
    AUTH_ADAPTER: str = "single_user"
    SINGLE_USER_SUBJECT: str = ""
    SINGLE_USER_NAME: str = ""
    SINGLE_USER_GROUPS: str = ""


@pytest.fixture
def single_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    return _SingleUserSettings()


@pytest.fixture
def templates(tmp_path):
    page = ("{{ page_title }} unread={{ unread_count }}\n"
            "{% for n in notifications %}N {{ n.message }} read={{ n.read }}\n{% endfor %}")
    for name in ("notifications_page.html", "notifications_panel.html"):
        (tmp_path / name).write_text(page, encoding="utf-8")
    (tmp_path / "notification_badge.html").write_text(
        "{% if count %}BADGE {{ count }}{% endif %}", encoding="utf-8")
    return Jinja2Templates(directory=tmp_path)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_every_request_is_the_default_local_user(single_settings, caplog):
    with caplog.at_level(logging.WARNING):
        app = build_app(single_settings)
    assert "only serve this app on localhost" in caplog.text

    @app.get("/whoami")
    async def whoami(user: Identity = Depends(require_page_identity())):
        return {"subject": user.subject, "name": user.display_name, "provider": user.provider}

    async def main():
        async with _client(app) as client:
            return await client.get("/whoami")

    response = asyncio.run(main())
    assert response.status_code == 200
    assert response.json() == {"subject": "local", "name": "Local user", "provider": "single_user"}
    assert single_user_identity(app) == Identity(
        subject="local", username="Local user", email=None, groups=[], claims={},
        display_name="Local user", provider="single_user")


def test_the_identity_comes_from_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    settings = _SingleUserSettings(SINGLE_USER_SUBJECT="me", SINGLE_USER_NAME="Sam",
                                   SINGLE_USER_GROUPS="admins, music")
    app = build_app(settings)
    user = single_user_identity(app)
    assert user is not None
    assert (user.subject, user.username, user.display_name, user.groups) == (
        "me", "Sam", "Sam", ["admins", "music"])


def test_other_adapters_have_no_single_user(settings):
    assert single_user_identity(build_app(settings)) is None


class _UnknownAdapterSettings(GTHBaseSettings):
    AUTH_ADAPTER: str = "nobody"


def test_an_unknown_adapter_still_raises(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    with pytest.raises(ValueError, match="single_user"):
        register_auth(FastAPI(), _UnknownAdapterSettings())


def test_notifications_work_without_sign_in(single_settings, templates):
    app = build_app(single_settings)
    store = InMemoryNotificationStore()
    register_notifications(app, single_settings, store=store,
                           views=NotificationViews(templates=templates))

    async def main():
        await notify(app, None, {"message": "Scan finished", "kind": "success"})
        async with _client(app) as client:
            page = await client.get("/notifications")
            badge = await client.get("/notifications/badge")
            marked = await client.post("/notifications/read-all")
            after = await client.get("/notifications/badge")
        return page, badge, marked, after

    page, badge, marked, after = asyncio.run(main())
    assert page.status_code == 200
    assert "unread=1" in page.text and "N Scan finished read=False" in page.text
    assert badge.text == "BADGE 1"
    assert marked.status_code == 204 and hx_triggers(marked)[NOTIFICATIONS_EVENT] == {"unread": 0}
    assert after.text == ""
    assert [n.recipient for n in store.list_for_sync("local")] == ["local"]


def test_notify_none_needs_single_user_mode(settings):
    app = build_app(settings)
    register_notifications(app, settings, store=InMemoryNotificationStore())
    with pytest.raises(ValueError, match="single_user"):
        asyncio.run(notify(app, None, {"message": "hi"}))
