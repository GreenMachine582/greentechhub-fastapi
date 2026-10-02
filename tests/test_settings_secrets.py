"""Secret settings through register_settings / SettingsViews (roadmap #20):
write-only on the page, encrypted in the store, the SECRET_SET marker in
every template and JSON value, and get_secret for server code."""

import pytest
from fastapi import Depends, FastAPI, Request
from greentechhub_core.permissions import Permission
from greentechhub_core.settings import (
    InMemorySettingsStore,
    SecretDecryptError,
    Setting,
    SettingScope,
    SettingsRegistry,
    SettingType,
)
from greentechhub_core.settings.builtins import PAGE_SIZE, THEME
from greentechhub_core.settings.crypto import FernetCipher

from greentechhub_fastapi import register_permissions, register_settings
from greentechhub_fastapi.settings import SettingsViews, get_effective_settings, get_secret
from tests.conftest import build_app
from tests.test_settings import ROLES, _get, _post, _run, role_settings, templates  # noqa: F401

PASSWORD = Setting(key="email.app_password", type=SettingType.STR, default="",
                   scope=SettingScope.USER, label="App password", secret=True)
API_TOKEN = Setting(key="billing.api_token", type=SettingType.STR, default="",
                    scope=SettingScope.APP, label="API token", secret=True,
                    edit_permission=Permission("settings.manage"))
PLAIN = "hunter2-plaintext"
KEY = FernetCipher.generate_key()


def _registry():
    return SettingsRegistry([THEME, PAGE_SIZE, PASSWORD, API_TOKEN])


def _app(role_settings, templates, *, store=None, cipher=None) -> FastAPI:  # noqa: F811
    app = build_app(role_settings)
    register_permissions(app, role_settings, roles=ROLES)
    register_settings(
        app, role_settings, registry=_registry(), store=store or InMemorySettingsStore(),
        views=SettingsViews(templates=templates), manage_permission="settings.manage",
        cipher=cipher or FernetCipher(KEY),
    )

    @app.get("/home")
    async def home(request: Request):
        return templates.TemplateResponse(request, "home.html", {"page_title": "Home",
                                                                 "settings_sections": []})

    @app.get("/api/effective")
    async def effective(values=Depends(get_effective_settings)):
        return {k: str(v) if v is not None else None for k, v in values.items()}

    @app.get("/api/password")
    async def password(value=Depends(get_secret("email.app_password"))):
        return {"value": value}

    @app.get("/api/token")
    async def token(value=Depends(get_secret("billing.api_token"))):
        return {"value": value}

    return app


def _flow(*steps):
    async def flow(client):
        return [await step(client) for step in steps]

    return flow


# startup


def test_a_secret_without_a_cipher_fails_at_startup(role_settings):  # noqa: F811
    app = build_app(role_settings)
    with pytest.raises(ValueError, match="email.app_password"):
        register_settings(app, role_settings, registry=_registry(),
                          store=InMemorySettingsStore())


# preferences


def test_saved_secret_is_encrypted_and_never_rendered(role_settings, templates):  # noqa: F811
    store = InMemorySettingsStore()
    app = _app(role_settings, templates, store=store)
    saved, page, home, effective, secret = _run(app, _flow(
        _post("/settings/preferences", {"email.app_password": PLAIN}),
        _get("/settings"),
        _get("/home"),
        _get("/api/effective", headers={}),
        _get("/api/password", headers={}),
    ), subject="alice")
    assert saved.status_code == 200 and "HX-Trigger" in saved.headers
    assert "VAL email.app_password=••••••••" in saved.text
    for response in (saved, page, home, effective):
        assert PLAIN not in response.text
    assert effective.json()["email.app_password"] == "••••••••"
    assert secret.json() == {"value": PLAIN}
    stored = store.get_many_sync(SettingScope.USER, "alice")["email.app_password"]
    assert PLAIN not in stored and FernetCipher(KEY).decrypt(stored) == PLAIN


def test_blank_keeps_and_clear_resets(role_settings, templates):  # noqa: F811
    app = _app(role_settings, templates)
    _, blank, kept, cleared, gone = _run(app, _flow(
        _post("/settings/preferences", {"email.app_password": PLAIN}),
        _post("/settings/preferences", {"email.app_password": "", "ui.page_size": "50"}),
        _get("/api/password", headers={}),
        _post("/settings/preferences", {"email.app_password": "",
                                        "email.app_password.__clear": "true"}),
        _get("/api/password", headers={}),
    ), subject="alice")
    assert blank.status_code == 200 and "VAL ui.page_size=50" in blank.text
    assert kept.json() == {"value": PLAIN}
    assert cleared.status_code == 200 and "VAL email.app_password=None" in cleared.text
    assert gone.json() == {"value": None}


def test_a_422_neither_stores_nor_echoes_the_secret(role_settings, templates):  # noqa: F811
    app = _app(role_settings, templates)
    invalid, secret = _run(app, _flow(
        _post("/settings/preferences", {"email.app_password": PLAIN, "ui.page_size": "500"}),
        _get("/api/password", headers={}),
    ), subject="alice")
    assert invalid.status_code == 422 and "ERR ui.page_size=" in invalid.text
    assert PLAIN not in invalid.text
    assert secret.json() == {"value": None}


def test_secrets_are_per_user(role_settings, templates):  # noqa: F811
    app = _app(role_settings, templates)
    _run(app, _post("/settings/preferences", {"email.app_password": PLAIN}), subject="alice")
    assert _run(app, _get("/api/password", headers={}), subject="bob").json() == {"value": None}
    assert _run(app, _get("/api/password", headers={})).json() == {"value": None}  # anonymous


# app section


def test_admin_sets_and_clears_an_app_secret(role_settings, templates):  # noqa: F811
    app = _app(role_settings, templates)
    saved, token, cleared, gone = _run(app, _flow(
        _post("/settings/app", {"billing.api_token": "tok-123"}),
        _get("/api/token", headers={}),
        _post("/settings/app", {"billing.api_token.__clear": "true"}),
        _get("/api/token", headers={}),
    ), subject="root")
    assert saved.status_code == 200 and "tok-123" not in saved.text
    assert token.json() == {"value": "tok-123"}
    assert cleared.status_code == 200 and gone.json() == {"value": None}


def test_app_secret_needs_the_permission(role_settings, templates):  # noqa: F811
    app = _app(role_settings, templates)
    denied = _run(app, _post("/settings/app", {"billing.api_token": "tok-123"}), subject="alice")
    assert denied.status_code == 403
    assert _run(app, _get("/api/token", headers={})).json() == {"value": None}


# get_secret


def test_get_secret_with_a_changed_key_raises(role_settings, templates):  # noqa: F811
    store = InMemorySettingsStore()
    _run(_app(role_settings, templates, store=store),
         _post("/settings/preferences", {"email.app_password": PLAIN}), subject="alice")
    rekeyed = _app(role_settings, templates, store=store,
                   cipher=FernetCipher(FernetCipher.generate_key()))
    with pytest.raises(SecretDecryptError):
        _run(rekeyed, _get("/api/password", headers={}), subject="alice")
    # the page still shows it as saved
    page = _run(rekeyed, _post("/settings/preferences", {}), subject="alice")
    assert "VAL email.app_password=••••••••" in page.text
