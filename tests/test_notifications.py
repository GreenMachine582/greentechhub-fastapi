"""register_notifications, notify() and NotificationViews: notices stored per
person from a toast payload (honouring delivery preferences), and the
signed-in user's page, panel, badge and mark-read actions."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from greentechhub_core.notifications import (
    InMemoryNotificationStore,
    new_notification,
    notification_preferences,
)
from greentechhub_core.settings import InMemorySettingsStore, SettingsRegistry

from greentechhub_fastapi import register_notifications, register_settings
from greentechhub_fastapi.notifications import (
    NOTIFICATIONS_EVENT,
    NotificationViews,
    notifications_nav_item,
    notify,
)
from greentechhub_fastapi.settings import get_settings_config
from greentechhub_fastapi.testing import hx_triggers
from tests.conftest import build_app
from tests.test_settings import _get, _post, _run, role_settings  # noqa: F401

# Stand-ins for greentechhub-ui's notification centre templates: they print the data.
LIST = """{{ page_title }} unread={{ unread_count }} only={{ unread_only }} \
all={{ mark_all_url }} page={{ page_url }}
{% for n in notifications %}N {{ n.message }} kind={{ n.kind }} read={{ n.read }} \
url={{ n.read_url }} toast={{ n.toast.message }}
{% endfor %}"""
BADGE = "{% if count %}BADGE {{ count }}{% endif %}"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def templates(tmp_path):
    for name in ("notifications_page.html", "notifications_panel.html"):
        (tmp_path / name).write_text(LIST, encoding="utf-8")
    (tmp_path / "notification_badge.html").write_text(BADGE, encoding="utf-8")
    return Jinja2Templates(directory=tmp_path)


def _app(role_settings, templates=None, *, preferences=None):  # noqa: F811
    app = build_app(role_settings)
    store = InMemoryNotificationStore()
    if preferences is not None:
        register_settings(app, role_settings, registry=SettingsRegistry(list(preferences)),
                          store=InMemorySettingsStore())
    views = NotificationViews(templates=templates) if templates is not None else None
    register_notifications(app, role_settings, store=store, views=views)
    return app, store


def _seed(store, recipient, message, minutes, *, read=False):
    notification = new_notification(recipient, message, now=T0 + timedelta(minutes=minutes))
    store.add_sync(notification)
    if read:
        store.mark_read_sync(recipient, [notification.id], at=T0 + timedelta(hours=1))
    return notification


class _Subject:
    def __init__(self, subject):
        self.subject = subject


# ── notify ─────────────────────────────────────────────────────────────────


def test_notify_stores_a_toast_payload_in_either_shape(role_settings):  # noqa: F811
    app, store = _app(role_settings)
    detail = {"message": "Sync finished", "kind": "success", "duration": 3000}
    first = asyncio.run(notify(app, "alice", detail, category="sync"))
    second = asyncio.run(notify(app, "alice", {"showToast": {"message": "Again"}}))
    assert first is not None and first.kind == "success" and first.category == "sync"
    assert second is not None and second.category == "general"
    assert [n.message for n in store.list_for_sync("alice")] == ["Again", "Sync finished"]


@pytest.mark.parametrize(("choice", "stored"), [
    ("in_app", True), ("both", True), ("email", False), ("off", False),
])
def test_notify_follows_the_delivery_preference(role_settings, choice, stored):  # noqa: F811
    preferences = notification_preferences({"sync": "Sync results"})
    app, store = _app(role_settings, preferences=preferences)
    settings = get_settings_config(app).settings
    settings.set_user_sync(_Subject("alice"), "notify.sync", choice)
    result = asyncio.run(notify(app, "alice", {"message": "Done"}, category="sync"))
    assert (result is not None) is stored
    assert len(store.list_for_sync("alice")) == (1 if stored else 0)
    # a category without a preference still lands in the app
    assert asyncio.run(notify(app, "alice", {"message": "Hi"}, category="other")) is not None


def test_notify_needs_register_notifications(role_settings):  # noqa: F811
    with pytest.raises(RuntimeError, match="register_notifications"):
        asyncio.run(notify(FastAPI(), "alice", {"message": "Hi"}))


# ── the views ──────────────────────────────────────────────────────────────


def test_the_page_lists_only_the_users_own_newest_first(role_settings, templates):  # noqa: F811
    app, store = _app(role_settings, templates)
    _seed(store, "alice", "Older", 1, read=True)
    newer = _seed(store, "alice", "Newer", 2)
    _seed(store, "bob", "Not yours", 3)
    page = _run(app, _get("/notifications"), subject="alice").text
    assert page.startswith("Notifications unread=1 only=False all=/notifications/read-all")
    assert page.index("N Newer") < page.index("N Older")
    assert f"url=/notifications/{newer.id}/read toast=Newer" in page
    assert "Not yours" not in page
    unread = _run(app, _get("/notifications?unread=1"), subject="alice").text
    assert "only=True" in unread and "N Newer" in unread and "N Older" not in unread


def test_the_panel_shows_the_newest_few(role_settings, templates):  # noqa: F811
    app, store = _app(role_settings, templates)
    for i in range(12):
        _seed(store, "alice", f"Note {i}", i)
    panel = _run(app, _get("/notifications/panel"), subject="alice").text
    assert panel.count("\nN ") == 10 and "N Note 11" in panel and "N Note 1 " not in panel


def test_the_badge_is_the_unread_count(role_settings, templates):  # noqa: F811
    app, store = _app(role_settings, templates)
    assert _run(app, _get("/notifications/badge"), subject="alice").text == ""
    _seed(store, "alice", "One", 1)
    _seed(store, "alice", "Two", 2)
    assert _run(app, _get("/notifications/badge"), subject="alice").text == "BADGE 2"
    anonymous = _run(app, _get("/notifications/badge"))
    assert anonymous.status_code == 204 and anonymous.text == ""


def test_marking_one_read_fires_the_event_with_the_new_count(role_settings, templates):  # noqa: F811
    app, store = _app(role_settings, templates)
    first = _seed(store, "alice", "One", 1)
    _seed(store, "alice", "Two", 2)
    response = _run(app, _post(f"/notifications/{first.id}/read", {}), subject="alice")
    assert response.status_code == 204
    assert hx_triggers(response) == {NOTIFICATIONS_EVENT: {"unread": 1}}


def test_nobody_can_mark_someone_elses_notification(role_settings, templates):  # noqa: F811
    app, store = _app(role_settings, templates)
    theirs = _seed(store, "bob", "Bob's", 1)
    _run(app, _post(f"/notifications/{theirs.id}/read", {}), subject="alice")
    assert store.unread_count_sync("bob") == 1


def test_mark_all_read(role_settings, templates):  # noqa: F811
    app, store = _app(role_settings, templates)
    _seed(store, "alice", "One", 1)
    _seed(store, "alice", "Two", 2)
    _seed(store, "bob", "Bob's", 3)
    response = _run(app, _post("/notifications/read-all", {}), subject="alice")
    assert hx_triggers(response) == {NOTIFICATIONS_EVENT: {"unread": 0}}
    assert store.unread_count_sync("alice") == 0 and store.unread_count_sync("bob") == 1


@pytest.mark.parametrize(("next_url", "redirect"), [
    ("/notifications?unread=1", "/notifications?unread=1"),
    ("https://evil.example/", None),
    ("//evil.example/", None),
])
def test_a_local_next_redirects_after_marking(role_settings, templates, next_url,  # noqa: F811
                                              redirect):
    app, store = _app(role_settings, templates)
    _seed(store, "alice", "One", 1)
    response = _run(app, _post("/notifications/read-all", {"next": next_url}), subject="alice")
    if redirect is None:
        assert response.status_code == 204
    else:
        assert response.status_code == 303 and response.headers["location"] == redirect
    assert store.unread_count_sync("alice") == 0


def test_anonymous_visitors_get_nothing(role_settings, templates):  # noqa: F811
    app, store = _app(role_settings, templates)
    _seed(store, "alice", "One", 1)
    assert _run(app, _get("/notifications")).status_code in (303, 401)
    assert _run(app, _post("/notifications/read-all", {})).status_code in (303, 401)
    assert store.unread_count_sync("alice") == 1


def test_the_nav_item_carries_the_live_badge():
    assert notifications_nav_item() == {
        "label": "Notifications", "url": "/notifications", "icon": "bell",
        "badge_url": "/notifications/badge", "badge_event": NOTIFICATIONS_EVENT,
    }


# ── the page context ───────────────────────────────────────────────────────


def _context_app(role_settings, tmp_path, *, views=True, url=None):  # noqa: F811
    from fastapi import Request
    from greentechhub_core.settings import InMemorySettingsStore, SettingsRegistry

    from greentechhub_fastapi.settings import settings_context

    (tmp_path / "ctx.html").write_text("BELL={{ notifications_url|default('unset') }}",
                                       encoding="utf-8")
    page_templates = Jinja2Templates(directory=tmp_path, context_processors=[settings_context])
    app = build_app(role_settings)
    register_settings(app, role_settings, registry=SettingsRegistry([]),
                      store=InMemorySettingsStore())
    notification_views = None
    if views:
        notification_views = NotificationViews(templates=page_templates)
        if url:
            notification_views.url = url
    register_notifications(app, role_settings, store=InMemoryNotificationStore(),
                           views=notification_views)

    @app.get("/page")
    async def page(request: Request):
        return page_templates.TemplateResponse(request, "ctx.html", {})

    return app


def test_signed_in_pages_point_the_bell_at_the_notification_centre(role_settings,  # noqa: F811
                                                                    tmp_path):
    app = _context_app(role_settings, tmp_path)
    assert _run(app, _get("/page"), subject="alice").text == "BELL=/notifications"
    assert _run(app, _get("/page")).text == "BELL=unset"  # anonymous


def test_no_bell_without_the_views_and_a_custom_url_is_kept(role_settings, tmp_path):  # noqa: F811
    bare = _context_app(role_settings, tmp_path, views=False)
    assert _run(bare, _get("/page"), subject="alice").text == "BELL=unset"
    custom = _context_app(role_settings, tmp_path, url="/inbox")
    assert _run(custom, _get("/page"), subject="alice").text == "BELL=/inbox"
