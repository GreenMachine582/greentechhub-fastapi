"""The events this package's views record once register_audit ran: sign-ins
(successful, failed, locked out), password changes and resets, role grants
and revokes, and settings changes (the keys, never a value)."""

import asyncio

import httpx
from fastapi import FastAPI
from greentechhub_core.audit import InMemoryAuditStore
from greentechhub_core.identity import DevelopmentIdentityProvider
from greentechhub_core.security import InMemoryAttemptStore, LoginThrottle

from greentechhub_fastapi import register_audit
from tests import test_role_admin, test_settings_password, test_settings_secrets
from tests.test_auth_reset import NEW, _request_link
from tests.test_auth_reset import _app as _reset_app
from tests.test_auth_reset import _call as _reset_call
from tests.test_auth_views import _FakeLoginViews, _make_templates
from tests.test_role_admin import _run as _roles_run
from tests.test_role_admin import role_settings  # noqa: F401
from tests.test_role_admin import templates as role_templates  # noqa: F401
from tests.test_settings import _post, _run
from tests.test_settings import role_settings as settings_role_settings  # noqa: F401
from tests.test_settings import templates as settings_templates  # noqa: F401


def _actions(store):
    return [(e.action, e.actor, e.target_id) for e in reversed(store.entries_sync())]


# sign-in


def _login_app(settings, throttle=None):
    app = FastAPI()
    store = InMemoryAuditStore()
    register_audit(app, settings, store=store)
    views = _FakeLoginViews(templates=_make_templates(),
                            identity_provider=DevelopmentIdentityProvider(secret_key="s"),
                            throttle=throttle)
    app.include_router(views.router())
    return app, store


def _login(app, user_id, password):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/login", data={"user_id": user_id, "password": password},
                                     follow_redirects=False)

    return asyncio.run(go())


def test_sign_ins_succeeded_and_failed(settings):
    app, store = _login_app(settings)
    assert _login(app, "alice", "wrong").status_code == 401
    assert _login(app, "alice", "s3cret").status_code == 303
    assert _actions(store) == [("auth.sign_in_failed", None, None),
                               ("auth.signed_in", "user-1", "user-1")]
    failed = store.entries_sync()[-1]
    assert failed.details == {"user_id": "alice"} and "wrong" not in str(failed.details)


def test_the_failure_that_trips_the_lock_and_attempts_while_locked(settings):
    throttle = LoginThrottle(InMemoryAttemptStore(), max_failures=2)
    app, store = _login_app(settings, throttle)
    assert _login(app, "alice", "wrong").status_code == 401
    assert _login(app, "alice", "wrong").status_code == 429  # trips the lock
    assert _login(app, "alice", "s3cret").status_code == 429  # refused while locked
    assert [a for a, _, _ in _actions(store)] == [
        "auth.sign_in_failed", "auth.locked_out", "auth.locked_out"]


# passwords


def test_a_password_reset(settings):
    app, views, sender = _reset_app()
    store = InMemoryAuditStore()
    register_audit(app, settings, store=store)
    token = _request_link(app, sender)
    assert _reset_call(app, "POST", f"/reset-password/{token}", NEW).status_code == 200
    assert _actions(store) == [("auth.password_reset", "alice", "alice")]


def test_a_password_change(settings_role_settings, settings_templates):  # noqa: F811
    app = test_settings_password._app(settings_role_settings, settings_templates,
                                      test_settings_password._Passwords())
    store = InMemoryAuditStore()
    register_audit(app, settings_role_settings, store=store)
    bad = dict(test_settings_password.GOOD, current_password="nope")
    _run(app, _post("/settings/password", bad), subject="alice")
    assert store.entries_sync() == []
    _run(app, _post("/settings/password", test_settings_password.GOOD), subject="alice")
    assert _actions(store) == [("auth.password_changed", "alice", "alice")]


# roles


def test_role_grants_and_revokes(role_settings, role_templates):  # noqa: F811
    app, _ = test_role_admin._app(role_settings, role_templates)
    store = InMemoryAuditStore()
    register_audit(app, role_settings, store=store)

    async def flow(client):
        await client.post("/admin/roles", data={"subject": "bob", "roles": ["viewer", "editor"]})
        await client.post("/admin/roles/bob", data={"roles": ["editor"]})
        await client.delete("/admin/roles/bob")

    _roles_run(app, flow, subject="root")
    entries = list(reversed(store.entries_sync()))
    assert [(e.action, e.actor, e.target_id, e.details["role"]) for e in entries] == [
        ("roles.granted", "root", "bob", "viewer"), ("roles.granted", "root", "bob", "editor"),
        ("roles.revoked", "root", "bob", "viewer"), ("roles.revoked", "root", "bob", "editor")]
    assert entries[0].summary == "Granted viewer to bob"


# settings


def test_settings_changes_record_keys_never_values(settings_role_settings,  # noqa: F811
                                                   settings_templates):  # noqa: F811
    app = test_settings_secrets._app(settings_role_settings, settings_templates)
    store = InMemoryAuditStore()
    register_audit(app, settings_role_settings, store=store)
    data = {"ui.theme": "dark", "ui.page_size": "25",  # 25 is the default: not a change
            "email.app_password": test_settings_secrets.PLAIN}
    _run(app, _post("/settings/preferences", data), subject="alice")
    # the form re-posted unchanged: the secret field comes back blank
    _run(app, _post("/settings/preferences", dict(data, **{"email.app_password": ""})),
         subject="alice")
    (entry,) = store.entries_sync()
    assert (entry.action, entry.actor, entry.target_type, entry.target_id) == (
        "settings.changed", "alice", "user", "alice")
    assert entry.details == {"section": "preferences",
                             "keys": ["email.app_password", "ui.theme"]}
    assert test_settings_secrets.PLAIN not in repr(entry)
