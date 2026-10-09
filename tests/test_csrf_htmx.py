"""CSRF beyond the auth forms (v0.16): register_csrf gives every request a
token (the gth_csrf cookie, set only when new) that ui_context passes to
templates; require_csrf checks the X-CSRF-Token header or the csrf_token
field on state-changing requests; SettingsViews(csrf=True),
RoleAdminViews(csrf=True) and LoginViews.logout_csrf opt in, and nothing
changes without them."""

import asyncio

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.settings import InMemorySettingsStore
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_csrf, register_permissions, register_settings
from greentechhub_fastapi.auth.csrf import CSRF_COOKIE_NAME, CSRF_HEADER, require_csrf
from greentechhub_fastapi.settings import SettingsViews
from greentechhub_fastapi.templating import ui_context
from tests import test_role_admin
from tests.conftest import build_app
from tests.test_auth_views import _FakeLoginViews
from tests.test_role_admin import role_settings  # noqa: F401
from tests.test_role_admin import templates as role_templates  # noqa: F401
from tests.test_settings import ROLES, _registry
from tests.test_settings import role_settings as settings_role_settings  # noqa: F401
from tests.test_settings import templates as settings_templates  # noqa: F401

TOKEN = "a" * 32


def _client(app, *, subject=None, token=None):
    cookies = {}
    if subject:
        provider = DevelopmentIdentityProvider(secret_key="test-secret")
        cookies["gth_session"] = provider.issue(
            Identity(subject=subject, username=subject, email=None, groups=[], claims={}))
    if token:
        cookies[CSRF_COOKIE_NAME] = token
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                             cookies=cookies)


def _call(app, method, path, *, subject=None, token=None, **kwargs):
    async def go():
        async with _client(app, subject=subject, token=token) as client:
            return await client.request(method, path, follow_redirects=False, **kwargs)

    return asyncio.run(go())


# middleware and context


def _plain_app():
    app = FastAPI()
    register_csrf(app)
    templates = Jinja2Templates(env=Environment(loader=DictLoader({"t.html": "{{ csrf_token }}"})),
                                context_processors=[ui_context])

    @app.get("/page")
    async def page(request: Request):
        return templates.TemplateResponse(request, "t.html", {})

    @app.post("/write", dependencies=[Depends(require_csrf)])
    async def write():
        return {"ok": True}

    @app.delete("/write", dependencies=[Depends(require_csrf)])
    async def delete():
        return {"ok": True}

    return app


def test_a_new_visitor_gets_a_token_cookie_matching_the_page():
    response = _call(_plain_app(), "GET", "/page")
    cookie = response.cookies[CSRF_COOKIE_NAME]
    assert response.text == cookie and len(cookie) >= 20
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "secure" in set_cookie and "samesite=lax" in set_cookie


def test_an_existing_token_is_reused_without_setting_the_cookie_again():
    response = _call(_plain_app(), "GET", "/page", token=TOKEN)
    assert response.text == TOKEN and "set-cookie" not in response.headers


def test_a_malformed_cookie_is_replaced():
    response = _call(_plain_app(), "GET", "/page", token="bad token!")
    assert response.cookies[CSRF_COOKIE_NAME] != "bad token!" and response.text != "bad token!"


def test_no_csrf_token_in_the_context_without_register_csrf():
    env = Environment(loader=DictLoader({"t.html": "[{{ csrf_token }}]"}))
    templates = Jinja2Templates(env=env, context_processors=[ui_context])
    app = FastAPI()

    @app.get("/page")
    async def page(request: Request):
        return templates.TemplateResponse(request, "t.html", {})

    assert _call(app, "GET", "/page").text == "[]"


def test_an_auth_form_shares_the_requests_token():
    app = _plain_app()
    views = _FakeLoginViews(
        templates=Jinja2Templates(env=Environment(loader=DictLoader(
            {"login_page.html": "{{ csrf_token }}"}))),
        identity_provider=DevelopmentIdentityProvider(secret_key="s"))
    views.csrf = True
    app.include_router(views.router())
    response = _call(app, "GET", "/login")
    assert len(response.headers.get_list("set-cookie")) == 1  # the form's, not a second one
    assert response.text == response.cookies[CSRF_COOKIE_NAME]


def test_register_csrf_after_start_is_refused():
    app = FastAPI()
    app.middleware_stack = app.build_middleware_stack()
    with pytest.raises(RuntimeError, match="before the app starts"):
        register_csrf(app)


# require_csrf


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_a_write_needs_the_token(method):
    app = _plain_app()
    assert _call(app, method, "/write", token=TOKEN).status_code == 403
    wrong = _call(app, method, "/write", token=TOKEN, headers={CSRF_HEADER: "b" * 32})
    assert wrong.status_code == 403 and "session expired" in wrong.text
    ok = _call(app, method, "/write", token=TOKEN, headers={CSRF_HEADER: TOKEN})
    assert ok.status_code == 200


def test_a_plain_form_can_send_the_field_instead():
    app = _plain_app()
    assert _call(app, "POST", "/write", token=TOKEN, data={"csrf_token": TOKEN}).status_code == 200
    assert _call(app, "POST", "/write", token=TOKEN, data={"csrf_token": "x"}).status_code == 403


def test_a_header_without_the_cookie_is_refused():
    assert _call(_plain_app(), "POST", "/write", headers={CSRF_HEADER: TOKEN}).status_code == 403


# the views' opt-ins


def _settings_app(settings, templates, csrf):
    app = build_app(settings)
    register_csrf(app)
    register_permissions(app, settings, roles=ROLES)
    register_settings(app, settings, registry=_registry(), store=InMemorySettingsStore(),
                      views=SettingsViews(templates=templates, csrf=csrf),
                      manage_permission="settings.manage")
    return app


def test_settings_writes_need_the_token_when_opted_in(settings_role_settings,  # noqa: F811
                                                      settings_templates):  # noqa: F811
    app = _settings_app(settings_role_settings, settings_templates, csrf=True)
    data = {"ui.theme": "dark"}
    assert _call(app, "GET", "/settings", subject="alice", token=TOKEN).status_code == 200
    refused = _call(app, "POST", "/settings/preferences", subject="alice", token=TOKEN, data=data)
    assert refused.status_code == 403
    saved = _call(app, "POST", "/settings/preferences", subject="alice", token=TOKEN, data=data,
                  headers={CSRF_HEADER: TOKEN, "HX-Request": "true"})
    assert saved.status_code == 200
    theme = _call(app, "POST", "/settings/theme", subject="alice", token=TOKEN,
                  data={"theme": "light"}, headers={CSRF_HEADER: TOKEN})
    assert theme.status_code == 204


def test_settings_are_unchanged_without_the_opt_in(settings_role_settings,  # noqa: F811
                                                   settings_templates):  # noqa: F811
    app = _settings_app(settings_role_settings, settings_templates, csrf=False)
    response = _call(app, "POST", "/settings/preferences", subject="alice",
                     data={"ui.theme": "dark"})
    assert response.status_code == 200


def test_role_writes_need_the_token_when_opted_in(role_settings, role_templates):  # noqa: F811
    app, store = test_role_admin._app(role_settings, role_templates, csrf=True)
    register_csrf(app)
    assign = {"subject": "bob", "roles": ["viewer"]}
    assert _call(app, "POST", "/admin/roles", subject="root", token=TOKEN,
                 data=assign).status_code == 403
    assert _call(app, "POST", "/admin/roles", subject="root", token=TOKEN, data=assign,
                 headers={CSRF_HEADER: TOKEN}).status_code == 200
    assert _call(app, "DELETE", "/admin/roles/bob", subject="root", token=TOKEN).status_code == 403
    assert asyncio.run(store.roles_for("bob")) == {"viewer"}
    assert _call(app, "DELETE", "/admin/roles/bob", subject="root", token=TOKEN,
                 headers={CSRF_HEADER: TOKEN}).status_code == 200
    assert asyncio.run(store.roles_for("bob")) == set()


def _login_app(logout_csrf):
    app = FastAPI()
    register_csrf(app)
    views = _FakeLoginViews(
        templates=Jinja2Templates(env=Environment(loader=DictLoader({"login_page.html": "x"}))),
        identity_provider=DevelopmentIdentityProvider(secret_key="s"))
    views.logout_csrf = logout_csrf
    app.include_router(views.router())
    return app


def test_logout_needs_the_token_when_opted_in():
    app = _login_app(logout_csrf=True)
    assert _call(app, "POST", "/logout", token=TOKEN).status_code == 403
    signed_out = _call(app, "POST", "/logout", token=TOKEN, data={"csrf_token": TOKEN})
    assert signed_out.status_code == 303 and signed_out.headers["location"] == "/login"


def test_logout_is_unchecked_by_default():
    assert _call(_login_app(logout_csrf=False), "POST", "/logout").status_code == 303
