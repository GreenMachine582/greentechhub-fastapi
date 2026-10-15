"""register_admin: mounts the admin views (once each) and returns greentechhub-ui's
"Admin" nav group, one child per view with its permission as required_permission."""

import asyncio

import httpx
import pytest
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from fastapi.templating import Jinja2Templates
from greentechhub_core.audit import InMemoryAuditStore
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.permissions import InMemoryGrantStore, Permission, Role

from greentechhub_fastapi import register_admin, register_audit, register_permissions
from greentechhub_fastapi.admin import admin_nav_item
from greentechhub_fastapi.audit import AuditViews
from greentechhub_fastapi.permissions import RoleAdminViews
from tests.conftest import build_app
from tests.test_role_admin import _Settings

MANAGE, VIEW = Permission("users.manage"), Permission("audit.view")
ROLES = (Role(name="admin", permissions={MANAGE, VIEW}), Role(name="auditor", permissions={VIEW}),
         Role(name="viewer", permissions=set()))


@pytest.fixture
def admin_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ROLE_BOOTSTRAP", "root=admin,ann=auditor,bob=viewer")
    return _Settings()


@pytest.fixture
def templates(tmp_path):
    (tmp_path / "roles_page.html").write_text("ROLES {{ page_title }}", encoding="utf-8")
    (tmp_path / "audit_page.html").write_text("AUDIT {{ page_title }}", encoding="utf-8")
    return Jinja2Templates(directory=tmp_path)


def _views(templates):
    return [RoleAdminViews(templates=templates, permission="users.manage"),
            AuditViews(templates=templates, permission="audit.view")]


def _app(settings, templates, *, audit_views_first=False, **kwargs):
    app = build_app(settings)
    register_permissions(app, settings, roles=ROLES, grants=InMemoryGrantStore())
    roles_views, audit_views = _views(templates)
    register_audit(app, settings, store=InMemoryAuditStore(),
                   views=audit_views if audit_views_first else None)
    nav = register_admin(app, settings, views=[roles_views, audit_views], **kwargs)
    return app, nav


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
            return await client.get(path, headers={"Accept": "text/html"}, follow_redirects=False)

    return asyncio.run(go())


def _visible(items, granted):
    """greentechhub-ui's rule (navigation.filter_by_scope) for a signed-in
    viewer, inlined since ui isn't a dependency: children need their
    required_permission, and a group without a url and with no children left
    is dropped."""
    result = []
    for item in items:
        if item.get("required_permission") and item["required_permission"] not in granted:
            continue
        if "children" in item:
            children = _visible(item["children"], granted)
            if not children and not item.get("url"):
                continue
            item = {**item, "children": children}
        result.append(item)
    return result


def test_the_group_has_one_child_per_view(admin_settings, templates):
    _, nav = _app(admin_settings, templates)
    assert nav == {
        "label": "Admin", "icon": "gear",
        "children": [
            {"label": "Roles", "url": "/admin/roles", "icon": "shield-lock",
             "required_permission": "users.manage"},
            {"label": "Audit log", "url": "/admin/audit", "icon": "journal-text",
             "required_permission": "audit.view"},
        ],
    }


def test_label_icon_and_view_overrides(templates):
    class Users(RoleAdminViews):
        url, title, icon = "/admin/users", "Users", "people"

    nav = admin_nav_item([Users(templates=templates, permission="users.manage")],
                         label="Manage", icon="tools")
    assert (nav["label"], nav["icon"]) == ("Manage", "tools")
    assert nav["children"] == [{"label": "Users", "url": "/admin/users", "icon": "people",
                                "required_permission": "users.manage"}]


def test_the_pages_are_mounted_and_gated(admin_settings, templates):
    app, _ = _app(admin_settings, templates)
    assert _get(app, "/admin/roles", "root").text == "ROLES Roles"
    assert _get(app, "/admin/audit", "ann").text == "AUDIT Audit log"
    assert _get(app, "/admin/roles", "ann").status_code == 403
    assert _get(app, "/admin/audit", "bob").status_code == 403
    assert _get(app, "/admin/audit").status_code in (302, 303, 307)


def test_a_view_register_audit_mounted_is_not_mounted_twice(admin_settings, templates,
                                                            monkeypatch):
    mounted = []
    original = AuditViews.router

    def counting(self):
        mounted.append(self.url)
        return original(self)

    monkeypatch.setattr(AuditViews, "router", counting)
    app, _ = _app(admin_settings, templates, audit_views_first=True)
    assert mounted == ["/admin/audit"]  # by register_audit, not again by register_admin
    assert _get(app, "/admin/audit", "ann").text == "AUDIT Audit log"


def test_only_viewers_with_an_admin_permission_see_the_group(admin_settings, templates):
    _, nav = _app(admin_settings, templates)
    everything = _visible([nav], {"users.manage", "audit.view"})
    assert [c["label"] for c in everything[0]["children"]] == ["Roles", "Audit log"]
    assert [c["label"] for c in _visible([nav], {"audit.view"})[0]["children"]] == ["Audit log"]
    assert _visible([nav], set()) == []


def test_a_services_own_admin_page_joins(admin_settings, templates):
    class Backups:
        url, title, icon, permission = "/admin/backups", "Backups", "archive", "users.manage"

        def router(self):
            router = APIRouter()
            router.add_api_route(self.url, lambda: PlainTextResponse("BACKUPS"), methods=["GET"])
            return router

    app = build_app(admin_settings)
    nav = register_admin(app, views=[Backups()])
    assert nav["children"][0]["url"] == "/admin/backups"
    assert _get(app, "/admin/backups").text == "BACKUPS"


def test_register_admin_must_run_before_the_app_starts(admin_settings, templates):
    app, _ = _app(admin_settings, templates)
    _get(app, "/admin/roles")
    with pytest.raises(RuntimeError, match="before the app starts"):
        register_admin(app, views=[])
