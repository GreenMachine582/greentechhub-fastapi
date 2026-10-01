import asyncio

import httpx
import pytest
from fastapi import Depends, FastAPI
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.permissions import InMemoryGrantStore, Permission, Role, RoleResolver

from greentechhub_fastapi import register_permissions
from greentechhub_fastapi.permissions import (
    get_granted_permissions,
    require_page_permission,
    require_permission,
)
from greentechhub_fastapi.registration.permissions import read_role_map
from tests.conftest import build_app

VIEW = Permission("reports.view")
MANAGE = Permission("settings.manage")
ROLES = (
    Role(name="viewer", permissions={VIEW}),
    Role(name="admin", permissions={VIEW, MANAGE}),
)


class _RoleSettings(GTHBaseSettings):
    AUTH_ADAPTER: str = "local"
    ROLE_GROUPS: str = ""
    ROLE_BOOTSTRAP: str = ""


@pytest.fixture
def role_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ROLE_BOOTSTRAP", "root-subject=admin")
    monkeypatch.setenv("ROLE_GROUPS", "staff=viewer")
    return _RoleSettings()


def _identity(subject: str, groups: list[str] | None = None) -> Identity:
    return Identity(subject=subject, username=subject, email=None, groups=groups or [], claims={})


def _app(settings, **register_kwargs) -> FastAPI:
    app = build_app(settings)
    register_permissions(app, settings, **({"roles": ROLES} | register_kwargs))

    @app.get("/api/admin")
    async def api_admin(user: Identity = Depends(require_permission("settings.manage"))):
        return {"subject": user.subject}

    @app.get("/admin")
    async def page_admin(user: Identity = Depends(require_page_permission("settings.manage"))):
        return {"subject": user.subject}

    @app.get("/granted")
    async def granted(perms=Depends(get_granted_permissions)):
        return sorted(perms)

    return app


def _get(app, settings, path, *, subject=None, groups=None, headers=None):
    cookies = None
    if subject is not None:
        provider = DevelopmentIdentityProvider(secret_key=settings.secret_key)
        cookies = {"gth_session": provider.issue(_identity(subject, groups))}

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", cookies=cookies
        ) as client:
            return await client.get(path, headers=headers, follow_redirects=False)

    return asyncio.run(run())


# the local-adapter flow: bootstrap subject allowed, normal user 403


def test_local_bootstrap_subject_is_allowed(role_settings):
    app = _app(role_settings)
    response = _get(app, role_settings, "/api/admin", subject="root-subject")
    assert response.status_code == 200
    assert response.json() == {"subject": "root-subject"}


def test_local_normal_user_gets_a_403_envelope(role_settings):
    response = _get(_app(role_settings), role_settings, "/api/admin", subject="someone")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_anonymous_api_caller_gets_401(role_settings):
    response = _get(_app(role_settings), role_settings, "/api/admin")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_group_roles_come_from_role_groups(role_settings):
    app = _app(role_settings)
    assert _get(app, role_settings, "/granted", subject="x", groups=["staff"]).json() == [VIEW]
    assert _get(app, role_settings, "/granted").json() == []


def test_grants_feed_the_built_resolver(role_settings):
    grants = InMemoryGrantStore({"granted-user": {"admin"}})
    app = _app(role_settings, grants=grants)
    response = _get(app, role_settings, "/api/admin", subject="granted-user")
    assert response.status_code == 200


# page routes


def test_page_route_redirects_anonymous_to_login(role_settings):
    response = _get(_app(role_settings), role_settings, "/admin")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_page_route_htmx_anonymous_gets_hx_redirect(role_settings):
    app = _app(role_settings)
    response = _get(app, role_settings, "/admin", headers={"HX-Request": "true"})
    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"


def test_page_route_forbids_without_the_permission(role_settings):
    app = _app(role_settings)
    assert _get(app, role_settings, "/admin", subject="someone").status_code == 403
    assert _get(app, role_settings, "/admin", subject="root-subject").status_code == 200


# registration


def test_a_custom_resolver_is_used_as_is(role_settings):
    resolver = RoleResolver(roles=ROLES, bootstrap={"other": ["admin"]})
    app = build_app(role_settings)
    assert register_permissions(app, role_settings, resolver=resolver) is resolver

    @app.get("/granted")
    async def granted(perms=Depends(get_granted_permissions)):
        return sorted(perms)

    assert _get(app, role_settings, "/granted", subject="other").json() == sorted([VIEW, MANAGE])
    assert _get(app, role_settings, "/granted", subject="root-subject").json() == []


def test_resolver_and_roles_together_is_an_error(role_settings):
    resolver = RoleResolver(roles=ROLES)
    with pytest.raises(ValueError, match="not both"):
        register_permissions(FastAPI(), role_settings, roles=ROLES, resolver=resolver)


def test_a_bootstrap_naming_an_unknown_role_fails_at_registration(role_settings, monkeypatch):
    monkeypatch.setenv("ROLE_BOOTSTRAP", "root-subject=superuser")
    with pytest.raises(ValueError, match="unknown role"):
        register_permissions(FastAPI(), _RoleSettings(), roles=ROLES)


def test_without_settings_or_roles_nobody_is_granted_anything(settings):
    app = build_app(settings)
    register_permissions(app, settings)

    @app.get("/granted")
    async def granted(perms=Depends(get_granted_permissions)):
        return sorted(perms)

    assert _get(app, settings, "/granted", subject="anyone").json() == []


def test_using_a_dependency_without_registering_raises(settings):
    app = build_app(settings)

    @app.get("/granted")
    async def granted(perms=Depends(get_granted_permissions)):
        return sorted(perms)

    with pytest.raises(RuntimeError, match="register_permissions"):
        _get(app, settings, "/granted")


def test_require_permission_rejects_a_malformed_permission_at_build_time():
    with pytest.raises(ValueError):
        require_permission("not a permission")
    with pytest.raises(ValueError):
        require_page_permission("settings")


def test_granted_permissions_are_resolved_once_per_request(role_settings):
    calls = []

    class CountingResolver:
        async def granted(self, identity):
            calls.append(identity)
            return frozenset({MANAGE})

        def granted_sync(self, identity):
            return frozenset({MANAGE})

    app = build_app(role_settings)
    register_permissions(app, role_settings, resolver=CountingResolver())

    @app.get("/twice")
    async def twice(
        a=Depends(require_permission("settings.manage")),
        b=Depends(require_page_permission("settings.manage")),
        perms=Depends(get_granted_permissions),
    ):
        return sorted(perms)

    assert _get(app, role_settings, "/twice", subject="x").status_code == 200
    assert len(calls) == 1


# read_role_map


class _Obj:
    def __init__(self, **values):
        self.__dict__.update(values)


@pytest.mark.parametrize(
    "value",
    [
        "alice=admin|editor,bob=viewer",
        " alice = admin | editor , bob=viewer ",
        '{"alice": ["admin", "editor"], "bob": "viewer"}',
        {"alice": ["admin", "editor"], "bob": ["viewer"]},
        {"alice": "admin,editor", "bob": "viewer"},
    ],
)
def test_read_role_map_accepts_every_form(value):
    expected = {"alice": ["admin", "editor"], "bob": ["viewer"]}
    assert read_role_map(_Obj(ROLE_BOOTSTRAP=value), "ROLE_BOOTSTRAP") == expected


@pytest.mark.parametrize("value", [None, "", {}])
def test_read_role_map_treats_missing_as_empty(value):
    assert read_role_map(_Obj(ROLE_BOOTSTRAP=value), "ROLE_BOOTSTRAP") == {}
    assert read_role_map(_Obj(), "ROLE_BOOTSTRAP") == {}


@pytest.mark.parametrize("value", ["alice", "=admin", "{not json", "[1]"])
def test_read_role_map_rejects_malformed_values(value):
    with pytest.raises(ValueError, match="ROLE_BOOTSTRAP"):
        read_role_map(_Obj(ROLE_BOOTSTRAP=value), "ROLE_BOOTSTRAP")
