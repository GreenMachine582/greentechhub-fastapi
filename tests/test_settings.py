import asyncio
import json

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.permissions import Permission, Role
from greentechhub_core.settings import (
    InMemorySettingsStore,
    Setting,
    SettingScope,
    SettingsRegistry,
    SettingType,
)
from greentechhub_core.settings.builtins import PAGE_SIZE, THEME

from greentechhub_fastapi import register_permissions, register_settings
from greentechhub_fastapi.settings import (
    SettingsContextMiddleware,
    SettingsViews,
    get_effective_settings,
    settings_context,
)
from tests.conftest import build_app

MANAGE = Permission("settings.manage")
ROLES = (Role(name="admin", permissions={MANAGE}),)
BANNER = Setting(key="site.banner", type=SettingType.STR, default="", scope=SettingScope.APP,
                 label="Maintenance banner")
MAINTENANCE = Setting(key="site.maintenance", type=SettingType.BOOL, default=False,
                      scope=SettingScope.APP, label="Maintenance mode")
HTML = {"Accept": "text/html"}

# Stand-ins for greentechhub-ui's settings_page.html / settings_section.html
# (this package doesn't depend on greentechhub-ui): they print the data.
PAGE = """PAGE {{ page_title }}
{% for section in settings_sections %}SECTION {{ section.id }} \
keys={{ section.settings|map(attribute='key')|join(',') }} action={{ section.action }}
{% endfor %}CTX user={{ current_user.username if current_user else 'none' }} \
theme={{ theme_mode|default('unset') }} save={{ theme_save_url|default('unset') }} \
menu={{ user_menu_items|default([])|map(attribute='url')|join(',') }} \
logout={{ logout_url|default('unset') }} granted={{ granted|default([])|sort|join(',') }}
"""
SECTION = """SECTION {{ section.id }}
{% for k, v in section['values']|dictsort %}VAL {{ k }}={{ v }}
{% endfor %}{% for k, v in (section.errors or {})|dictsort %}ERR {{ k }}={{ v|join(';') }}
{% endfor %}"""


class _Settings(GTHBaseSettings):
    AUTH_ADAPTER: str = "local"
    ROLE_BOOTSTRAP: str = ""


class _CountingStore(InMemorySettingsStore):
    def __init__(self):
        super().__init__()
        self.reads = 0

    async def get_many(self, scope, subject):
        self.reads += 1
        return await super().get_many(scope, subject)


@pytest.fixture
def role_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ROLE_BOOTSTRAP", "root=admin")
    return _Settings()


@pytest.fixture
def templates(tmp_path):
    (tmp_path / "settings_page.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "settings_section.html").write_text(SECTION, encoding="utf-8")
    (tmp_path / "home.html").write_text(PAGE, encoding="utf-8")
    return Jinja2Templates(directory=tmp_path, context_processors=[settings_context])


def _registry():
    return SettingsRegistry([THEME, PAGE_SIZE, BANNER, MAINTENANCE])


def _app(role_settings, templates, *, store=None, manage=True, views=True) -> FastAPI:
    app = build_app(role_settings)
    register_permissions(app, role_settings, roles=ROLES)
    register_settings(
        app, role_settings, registry=_registry(), store=store or InMemorySettingsStore(),
        views=SettingsViews(templates=templates) if views else None,
        manage_permission="settings.manage" if manage else None, logout_url="/logout",
    )

    @app.get("/home")
    async def home(request: Request):
        return templates.TemplateResponse(request, "home.html", {"page_title": "Home",
                                                                 "settings_sections": []})

    @app.get("/api/effective")
    async def effective(values=Depends(get_effective_settings)):
        return values

    return app


def _run(app, flow, subject=None):
    async def go():
        cookies = None
        if subject:
            provider = DevelopmentIdentityProvider(secret_key="test-secret")
            identity = Identity(subject=subject, username=subject, email=None, groups=[],
                                claims={})
            cookies = {"gth_session": provider.issue(identity)}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     cookies=cookies) as client:
            return await flow(client)

    return asyncio.run(go())


def _get(path, headers=HTML):
    return lambda client: client.get(path, headers=headers)


def _post(path, data, headers=HTML):
    return lambda client: client.post(path, data=data, headers=headers)


# ── context processor ──────────────────────────────────────────────────────


def test_anonymous_page_gets_no_user_and_no_theme(role_settings, templates):
    html = _run(_app(role_settings, templates), _get("/home")).text
    assert "user=none theme=unset save=unset menu= logout=unset granted=" in html


def test_signed_in_page_gets_the_ui_keys(role_settings, templates):
    html = _run(_app(role_settings, templates), _get("/home"), subject="root").text
    assert ("user=root theme=system save=/settings/theme menu=/settings logout=/logout "
            "granted=settings.manage") in html


def test_without_views_there_is_no_menu_link_or_theme_save(role_settings, templates):
    html = _run(_app(role_settings, templates, views=False), _get("/home"), subject="alice").text
    assert "theme=system save=unset menu= logout=/logout" in html


def test_json_and_static_requests_skip_the_store(role_settings, templates):
    store = _CountingStore()
    app = _app(role_settings, templates, store=store)
    response = _run(app, _get("/api/effective", headers={"Accept": "application/json"}),
                    subject="alice")
    assert response.json()["ui.page_size"] == 25
    reads_for_json = store.reads
    _run(app, _get("/home"), subject="alice")
    assert store.reads > reads_for_json  # only the page request ran the middleware


def test_middleware_is_innermost(role_settings, templates):
    app = _app(role_settings, templates)
    assert app.user_middleware[-1].cls is SettingsContextMiddleware


# ── the page ───────────────────────────────────────────────────────────────


def test_anonymous_settings_page_redirects_to_login(role_settings, templates):
    response = _run(_app(role_settings, templates), _get("/settings"))
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_user_sees_preferences_only(role_settings, templates):
    html = _run(_app(role_settings, templates), _get("/settings"), subject="alice").text
    assert "PAGE Settings" in html
    assert "SECTION preferences keys=ui.theme,ui.page_size action=/settings/preferences" in html
    assert "SECTION app" not in html


def test_bootstrap_admin_also_sees_app(role_settings, templates):
    html = _run(_app(role_settings, templates), _get("/settings"), subject="root").text
    assert "SECTION app keys=site.banner,site.maintenance action=/settings/app" in html


def test_no_manage_permission_means_no_app_section(role_settings, templates):
    html = _run(_app(role_settings, templates, manage=False), _get("/settings"),
                subject="root").text
    assert "SECTION app" not in html


# ── saves ──────────────────────────────────────────────────────────────────


def test_preferences_save_stores_and_sends_the_theme_event(role_settings, templates):
    store = InMemorySettingsStore()
    app = _app(role_settings, templates, store=store)
    response = _run(app, _post("/settings/preferences",
                               {"ui.theme": "light", "ui.page_size": "50"}), subject="alice")
    assert response.status_code == 200
    trigger = json.loads(response.headers["HX-Trigger"])
    assert trigger["showToast"]["message"] == "Preferences saved"
    assert trigger["gth:theme"] == "light"
    assert "VAL ui.page_size=50" in response.text
    saved = asyncio.run(store.get_many(SettingScope.USER, "alice"))
    assert saved == {"ui.theme": "light", "ui.page_size": 50}


def test_saving_the_defaults_stores_nothing(role_settings, templates):
    store = InMemorySettingsStore()
    app = _app(role_settings, templates, store=store)

    async def flow(client):
        await client.post("/settings/preferences", data={"ui.theme": "dark", "ui.page_size": "50"},
                          headers=HTML)
        return await client.post("/settings/preferences",
                                 data={"ui.theme": "system", "ui.page_size": "25"}, headers=HTML)

    response = _run(app, flow, subject="alice")
    assert json.loads(response.headers["HX-Trigger"])["gth:theme"] == "system"
    assert asyncio.run(store.get_many(SettingScope.USER, "alice")) == {}


def test_no_theme_event_when_the_theme_is_unchanged(role_settings, templates):
    response = _run(_app(role_settings, templates),
                    _post("/settings/preferences", {"ui.theme": "system", "ui.page_size": "30"}),
                    subject="alice")
    assert "gth:theme" not in json.loads(response.headers["HX-Trigger"])


def test_invalid_preference_is_a_422_and_nothing_is_stored(role_settings, templates):
    store = InMemorySettingsStore()
    response = _run(_app(role_settings, templates, store=store),
                    _post("/settings/preferences", {"ui.theme": "light", "ui.page_size": "500"}),
                    subject="alice")
    assert response.status_code == 422
    assert "ERR ui.page_size=" in response.text
    assert "VAL ui.page_size=500" in response.text
    assert "HX-Trigger" not in response.headers
    assert asyncio.run(store.get_many(SettingScope.USER, "alice")) == {}


def test_app_save_needs_the_permission(role_settings, templates):
    store = InMemorySettingsStore()
    app = _app(role_settings, templates, store=store)
    denied = _run(app, _post("/settings/app", {"site.banner": "Down at 5"}), subject="alice")
    assert denied.status_code == 403
    allowed = _run(app, _post("/settings/app", {"site.banner": "Down at 5",
                                                "site.maintenance": "true"}), subject="root")
    assert allowed.status_code == 200
    assert json.loads(allowed.headers["HX-Trigger"])["showToast"]["message"] == "App saved"
    assert asyncio.run(store.get_many(SettingScope.APP, None)) == {
        "site.banner": "Down at 5", "site.maintenance": True}


def test_unchecked_bool_without_off_value_saves_false(role_settings, templates):
    store = InMemorySettingsStore()
    app = _app(role_settings, templates, store=store)
    _run(app, _post("/settings/app", {"site.banner": "", "site.maintenance": "true"}),
         subject="root")
    _run(app, _post("/settings/app", {"site.banner": ""}), subject="root")
    assert asyncio.run(store.get_many(SettingScope.APP, None))["site.maintenance"] is False


def test_invalid_app_value_is_a_422(role_settings, templates):
    response = _run(_app(role_settings, templates),
                    _post("/settings/app", {"site.banner": "", "site.maintenance": "maybe"}),
                    subject="root")
    assert response.status_code == 422
    assert "ERR site.maintenance=" in response.text


def test_theme_endpoint(role_settings, templates):
    store = InMemorySettingsStore()
    app = _app(role_settings, templates, store=store)
    assert _run(app, _post("/settings/theme", {"theme": "light"}), subject="alice").status_code \
        == 204
    assert asyncio.run(store.get_many(SettingScope.USER, "alice")) == {"ui.theme": "light"}
    assert _run(app, _post("/settings/theme", {"theme": "purple"}),
                subject="alice").status_code == 422
    assert _run(app, _post("/settings/theme", {"theme": "light"})).status_code == 401
    # the next page carries it as theme_mode
    assert "theme=light" in _run(app, _get("/home"), subject="alice").text


# ── startup ────────────────────────────────────────────────────────────────


def test_manage_permission_needs_register_permissions(role_settings):
    app = build_app(role_settings)
    with pytest.raises(RuntimeError, match="register_permissions"):
        register_settings(app, role_settings, registry=_registry(),
                          store=InMemorySettingsStore(), manage_permission="settings.manage")


def test_a_malformed_manage_permission_fails_at_startup(role_settings):
    app = build_app(role_settings)
    with pytest.raises(ValueError):
        register_settings(app, role_settings, registry=_registry(),
                          store=InMemorySettingsStore(), manage_permission="settings")


def test_register_after_start_fails(role_settings, templates):
    app = _app(role_settings, templates)
    _run(app, _get("/home"))  # builds the middleware stack
    with pytest.raises(RuntimeError, match="before the app starts"):
        register_settings(app, role_settings, registry=_registry(), store=InMemorySettingsStore())
