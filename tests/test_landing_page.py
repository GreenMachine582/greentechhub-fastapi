"""The landing-page redirect (roadmap #21): LoginViews sends a login to the
user's ui.landing_page (core's landing_page_setting) when register_settings
registered it, else to redirect_url; landing_url for a service's own routes."""

from fastapi import Depends, FastAPI, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.settings import (
    InMemorySettingsStore,
    SettingScope,
    SettingsRegistry,
)
from greentechhub_core.settings.builtins import LANDING_PAGE_KEY, THEME, landing_page_setting
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_settings
from greentechhub_fastapi.auth import LoginViews, get_current_user
from greentechhub_fastapi.settings import landing_url
from tests.conftest import build_app
from tests.test_settings import _get, _run, role_settings  # noqa: F401

ALICE = Identity(subject="alice", username="alice", email=None, groups=[], claims={})
PAGES = {"/": "Home", "/reports": "Reports"}
LANDING = landing_page_setting(PAGES, default="/reports")


class _Login(LoginViews):
    async def authenticate(self, user_id, password):
        return ALICE if (user_id, password) == ("alice", "pw") else None


def _app(role_settings, *, registry=None, store=None, settings=True, **attrs) -> FastAPI:  # noqa: F811
    app = build_app(role_settings)
    if settings:
        register_settings(
            app, role_settings,
            registry=registry or SettingsRegistry([LANDING]),
            store=store or InMemorySettingsStore(),
        )
    templates = Jinja2Templates(env=Environment(loader=DictLoader({"login.html": "Log in"})))
    views = _Login(templates=templates,
                   identity_provider=DevelopmentIdentityProvider(secret_key="test-secret"))
    for key, value in attrs.items():
        setattr(views, key, value)
    app.include_router(views.router())

    @app.get("/home")
    async def home(request: Request, user=Depends(get_current_user)):
        return {"url": await landing_url(request, user, fallback="/dashboard")}

    return app


def _login(app):
    async def flow(client):
        return await client.post("/login", data={"user_id": "alice", "password": "pw"},
                                 follow_redirects=False)

    response = _run(app, flow)
    assert response.status_code == 303
    return response.headers["location"]


# LoginViews


def test_login_lands_on_the_settings_default(role_settings):  # noqa: F811
    assert _login(_app(role_settings)) == "/reports"


def test_login_lands_on_the_users_choice(role_settings):  # noqa: F811
    store = InMemorySettingsStore()
    store.set_sync(SettingScope.USER, "alice", LANDING_PAGE_KEY, "/")
    assert _login(_app(role_settings, store=store)) == "/"


def test_the_app_value_applies_without_a_users_own(role_settings):  # noqa: F811
    store = InMemorySettingsStore()
    store.set_sync(SettingScope.APP, None, LANDING_PAGE_KEY, "/")
    assert _login(_app(role_settings, store=store)) == "/"


def test_a_stale_page_falls_back_to_the_default(role_settings):  # noqa: F811
    store = InMemorySettingsStore()
    store.set_sync(SettingScope.USER, "alice", LANDING_PAGE_KEY, "/gone")
    assert _login(_app(role_settings, store=store)) == "/reports"


def test_without_register_settings_redirect_url_applies(role_settings):  # noqa: F811
    assert _login(_app(role_settings, settings=False)) == "/"
    assert _login(_app(role_settings, settings=False, redirect_url="/start")) == "/start"


def test_without_the_landing_setting_redirect_url_applies(role_settings):  # noqa: F811
    app = _app(role_settings, registry=SettingsRegistry([THEME]), redirect_url="/start")
    assert _login(app) == "/start"


# landing_url on a service's own route


def test_landing_url_for_a_signed_in_user(role_settings):  # noqa: F811
    store = InMemorySettingsStore()
    store.set_sync(SettingScope.USER, "alice", LANDING_PAGE_KEY, "/")
    response = _run(_app(role_settings, store=store), _get("/home", headers={}), subject="alice")
    assert response.json() == {"url": "/"}


def test_landing_url_anonymous_gets_the_default(role_settings):  # noqa: F811
    assert _run(_app(role_settings), _get("/home", headers={})).json() == {"url": "/reports"}


def test_landing_url_without_the_setting_is_the_fallback(role_settings):  # noqa: F811
    app = _app(role_settings, settings=False)
    assert _run(app, _get("/home", headers={}), subject="alice").json() == {"url": "/dashboard"}
