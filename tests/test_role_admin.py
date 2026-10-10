import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.permissions import InMemoryGrantStore, Permission, Role

from greentechhub_fastapi import register_permissions
from greentechhub_fastapi.permissions import RoleAdminViews
from greentechhub_fastapi.testing import hx_triggers
from tests.conftest import build_app

MANAGE = Permission("users.manage")
ROLES = (
    Role(name="viewer", permissions=set()),
    Role(name="editor", permissions=set()),
    Role(name="admin", permissions={MANAGE}),
)

# Stand-ins for greentechhub-ui's roles_page.html / roles_section.html (this
# package doesn't depend on greentechhub-ui): they print the data.
SECTION = """URL {{ roles_url }}
OPTIONS {{ roles_options|map(attribute='value')|join(',') }}
{% for row in roles_assignments %}ROW {{ row.subject }}={{ row.roles|join(',') }}
{% endfor %}{% if roles_form %}FORM {{ roles_form.subject }} {{ roles_form.roles|join(',') }}
{% for k, v in roles_form.errors|dictsort %}ERR {{ k }}={{ v|join(';') }}
{% endfor %}{% endif %}"""
PAGE = "PAGE {{ page_title }}\n" + SECTION


class _Settings(GTHBaseSettings):
    AUTH_ADAPTER: str = "local"
    ROLE_BOOTSTRAP: str = ""


@pytest.fixture
def role_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ROLE_BOOTSTRAP", "root=admin")
    return _Settings()


@pytest.fixture
def templates(tmp_path):
    (tmp_path / "roles_page.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "roles_section.html").write_text(SECTION, encoding="utf-8")
    return Jinja2Templates(directory=tmp_path)


def _app(
    role_settings, templates, store=None, **views_kwargs
) -> tuple[FastAPI, InMemoryGrantStore]:
    store = store if store is not None else InMemoryGrantStore()
    app = build_app(role_settings)
    register_permissions(app, role_settings, roles=ROLES, grants=store)
    views = RoleAdminViews(templates=templates, permission="users.manage", **views_kwargs)
    app.include_router(views.router())
    return app, store


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


def _trigger(response) -> str:
    return hx_triggers(response)["showToast"]["message"]


# ── the permission gate ────────────────────────────────────────────────────


def test_anonymous_is_sent_to_login(role_settings, templates):
    app, _ = _app(role_settings, templates)
    page = _run(app, lambda c: c.get("/admin/roles"))
    assert (page.status_code, page.headers["location"]) == (303, "/login")
    htmx = _run(app, lambda c: c.get("/admin/roles", headers={"HX-Request": "true"}))
    assert (htmx.status_code, htmx.headers["HX-Redirect"]) == (401, "/login")


def test_a_user_without_the_permission_gets_403_everywhere(role_settings, templates):
    app, store = _app(role_settings, templates)
    store.assign_sync("carol", "viewer")
    for method, path, data in (("GET", "/admin/roles", None),
                               ("POST", "/admin/roles", {"subject": "x", "roles": "admin"}),
                               ("POST", "/admin/roles/carol", {"roles": "admin"}),
                               ("DELETE", "/admin/roles/carol", None)):
        response = _run(app, lambda c, m=method, p=path, d=data: c.request(m, p, data=d),
                        subject="alice")
        assert response.status_code == 403, (method, path)
    assert store.roles_for_sync("carol") == frozenset({"viewer"})
    assert store.roles_for_sync("x") == frozenset()


def test_bootstrap_admin_sees_the_page(role_settings, templates):
    app, store = _app(role_settings, templates)
    store.assign_sync("zed", "editor")
    store.assign_sync("amy", "viewer")
    store.assign_sync("amy", "admin")
    html = _run(app, lambda c: c.get("/admin/roles"), subject="root").text
    assert "PAGE Roles" in html
    assert "URL /admin/roles" in html
    assert "OPTIONS viewer,editor,admin" in html
    assert html.index("ROW amy=admin,viewer") < html.index("ROW zed=editor")


# ── writes ─────────────────────────────────────────────────────────────────


def test_assign_stores_the_known_roles(role_settings, templates):
    app, store = _app(role_settings, templates)
    response = _run(app, lambda c: c.post("/admin/roles", data={
        "subject": " carol ", "roles": ["editor", "viewer", "superuser"]}), subject="root")
    assert response.status_code == 200
    assert _trigger(response) == "Roles assigned to carol"
    assert "ROW carol=editor,viewer" in response.text
    assert store.roles_for_sync("carol") == frozenset({"viewer", "editor"})


def test_assign_needs_a_subject_and_a_role(role_settings, templates):
    app, store = _app(role_settings, templates)
    response = _run(app, lambda c: c.post("/admin/roles", data={"subject": " ",
                                                                "roles": "superuser"}),
                    subject="root")
    assert response.status_code == 422
    assert "ERR roles=Pick at least one role." in response.text
    assert "ERR subject=Enter a user ID." in response.text
    assert "HX-Trigger" not in response.headers
    assert dict(store.list_assignments_sync()) == {}


def test_set_makes_the_known_roles_exactly_the_checked_ones(role_settings, templates):
    store = InMemoryGrantStore({"carol": {"viewer", "editor", "retired-role"}})
    app, _ = _app(role_settings, templates, store=store)
    response = _run(app, lambda c: c.post("/admin/roles/carol",
                                          data={"roles": ["editor", "admin"]}), subject="root")
    assert response.status_code == 200
    assert _trigger(response) == "Roles saved for carol"
    # viewer revoked, admin added, editor kept, the unknown stored name left alone
    assert store.roles_for_sync("carol") == frozenset({"editor", "admin", "retired-role"})


def test_set_with_nothing_checked_revokes_the_known_roles(role_settings, templates):
    store = InMemoryGrantStore({"carol": {"viewer"}})
    app, _ = _app(role_settings, templates, store=store)
    _run(app, lambda c: c.post("/admin/roles/carol", data={}), subject="root")
    assert store.roles_for_sync("carol") == frozenset()


def test_subjects_with_a_slash_work_through_percent_encoding(role_settings, templates):
    store = InMemoryGrantStore({"bob/ops": {"viewer"}})
    app, _ = _app(role_settings, templates, store=store)
    _run(app, lambda c: c.post("/admin/roles/bob%2Fops", data={"roles": "admin"}), subject="root")
    assert store.roles_for_sync("bob/ops") == frozenset({"admin"})
    removed = _run(app, lambda c: c.delete("/admin/roles/bob%2Fops"), subject="root")
    assert _trigger(removed) == "Removed bob/ops's roles"
    assert store.roles_for_sync("bob/ops") == frozenset()


def test_remove_revokes_everything(role_settings, templates):
    store = InMemoryGrantStore({"carol": {"viewer", "retired-role"}, "dave": {"editor"}})
    app, _ = _app(role_settings, templates, store=store)
    response = _run(app, lambda c: c.delete("/admin/roles/carol"), subject="root")
    assert response.status_code == 200
    assert "ROW carol" not in response.text and "ROW dave=editor" in response.text
    assert dict(store.list_assignments_sync()) == {"dave": frozenset({"editor"})}


# ── wiring ─────────────────────────────────────────────────────────────────


def test_a_missing_grant_store_is_a_clear_error(role_settings, templates):
    app = build_app(role_settings)
    register_permissions(app, role_settings, roles=ROLES)  # no grants=
    app.include_router(RoleAdminViews(templates=templates, permission="users.manage").router())
    with pytest.raises(RuntimeError, match="needs a GrantStore"):
        _run(app, lambda c: c.get("/admin/roles"), subject="root")


def test_explicit_roles_and_grants_win(role_settings, templates):
    other = InMemoryGrantStore({"eve": {"auditor"}})
    app, store = _app(role_settings, templates, roles=[Role(name="auditor", permissions=set())],
                      grants=other)
    html = _run(app, lambda c: c.get("/admin/roles"), subject="root").text
    assert "OPTIONS auditor" in html and "ROW eve=auditor" in html


def test_a_malformed_permission_fails_when_built(templates):
    with pytest.raises(ValueError):
        RoleAdminViews(templates=templates, permission="users")
