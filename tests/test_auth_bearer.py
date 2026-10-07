"""Bearer tokens for API routes: register_auth(..., bearer=True) resolves
`Authorization: Bearer` through the local adapter's provider, issue_token
signs one, and bearer_scheme documents it in OpenAPI."""

import asyncio
from datetime import timedelta

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, Form, Request
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.identity import Identity
from greentechhub_core.permissions import Permission, Role
from greentechhub_core.types import UnauthorizedError

from greentechhub_fastapi import (
    register_api_error_handlers,
    register_auth,
    register_exception_handlers,
    register_permissions,
)
from greentechhub_fastapi.auth import bearer_scheme, issue_token
from greentechhub_fastapi.auth.cookies import SESSION_COOKIE_NAME
from greentechhub_fastapi.dependencies import get_current_identity
from greentechhub_fastapi.permissions import require_permission

VIEW = Permission("things.view")
ROLES = (Role(name="viewer", permissions={VIEW}),)


class _Settings(GTHBaseSettings):
    pass


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ROLE_BOOTSTRAP", "alice=viewer")
    for name in ("AUTH_ADAPTER", "ROLE_GROUPS"):
        monkeypatch.delenv(name, raising=False)
    return _Settings(_env_file=None)


def _identity(subject: str) -> Identity:
    return Identity(subject=subject, username=subject, email=None, groups=[], claims={})


def _app(settings, *, bearer: bool) -> FastAPI:
    """A PyFinBot-shaped API: an OAuth2 password login issuing a token, and
    bearer-protected routes."""
    app = FastAPI()
    register_exception_handlers(app)
    register_api_error_handlers(app, prefix="/api")
    register_auth(app, settings, bearer=bearer)
    register_permissions(app, settings, roles=ROLES)
    api = APIRouter(prefix="/api", dependencies=[Depends(bearer_scheme("/api/auth/login"))])

    @api.post("/auth/login")
    async def login(request: Request, username: str = Form(...), password: str = Form(...)):
        if password != "s3cret":
            raise UnauthorizedError("Incorrect user ID or password")
        return {"access_token": issue_token(request, _identity(username)), "token_type": "bearer"}

    @api.get("/me")
    async def me(identity: Identity = Depends(get_current_identity)):
        return {"subject": identity.subject}

    @api.get("/things")
    async def things(identity: Identity = Depends(require_permission("things.view"))):
        return {"subject": identity.subject}

    app.include_router(api)
    return app


def _call(app, method, url, **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(run())


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_a_token_from_the_login_route_works_as_a_bearer_token(settings):
    app = _app(settings, bearer=True)
    login = _call(app, "POST", "/api/auth/login", data={"username": "alice", "password": "s3cret"})
    token = login.json()["access_token"]
    assert _call(app, "GET", "/api/me", headers=_bearer(token)).json() == {"subject": "alice"}


def test_require_permission_works_over_bearer(settings):
    app = _app(settings, bearer=True)
    alice = issue_token(app, _identity("alice"))
    bob = issue_token(app, _identity("bob"))
    assert _call(app, "GET", "/api/things", headers=_bearer(alice)).status_code == 200
    assert _call(app, "GET", "/api/things", headers=_bearer(bob)).status_code == 403


def test_no_or_a_bad_token_is_the_401_envelope(settings):
    app = _app(settings, bearer=True)
    for headers in ({}, _bearer("not-a-jwt"), {"Authorization": "Basic abc"}):
        resp = _call(app, "GET", "/api/me", headers=headers)
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"
        assert resp.json()["code"] == "unauthorized"


def test_an_expired_token_is_refused(settings):
    app = _app(settings, bearer=True)
    token = issue_token(app, _identity("alice"), expires_in=timedelta(seconds=-1))
    assert _call(app, "GET", "/api/me", headers=_bearer(token)).status_code == 401


def test_without_bearer_the_header_is_ignored(settings):
    app = _app(settings, bearer=False)
    token = issue_token(app, _identity("alice"))
    assert _call(app, "GET", "/api/me", headers=_bearer(token)).status_code == 401
    # the session cookie still works as before
    resp = _call(app, "GET", "/api/me", cookies={SESSION_COOKIE_NAME: token})
    assert resp.json() == {"subject": "alice"}


def test_the_header_decides_when_present(settings):
    # a bad bearer token doesn't fall back to a good cookie
    app = _app(settings, bearer=True)
    good = issue_token(app, _identity("alice"))
    resp = _call(app, "GET", "/api/me", headers=_bearer("bad"), cookies={SESSION_COOKIE_NAME: good})
    assert resp.status_code == 401
    resp = _call(app, "GET", "/api/me", cookies={SESSION_COOKIE_NAME: good})
    assert resp.json() == {"subject": "alice"}


def test_issue_token_needs_the_local_adapter(monkeypatch, settings):
    with pytest.raises(RuntimeError, match="AUTH_ADAPTER=local"):
        issue_token(FastAPI(), _identity("alice"))
    monkeypatch.setenv("AUTH_ADAPTER", "forward_auth")
    app = FastAPI()
    register_auth(app, _Settings(_env_file=None), bearer=True)  # forward_auth ignores bearer
    with pytest.raises(RuntimeError):
        issue_token(app, _identity("alice"))


def test_bearer_scheme_is_in_openapi(settings):
    schema = _app(settings, bearer=True).openapi()
    schemes = schema["components"]["securitySchemes"]
    assert any(s["type"] == "oauth2" and s["flows"]["password"]["tokenUrl"] == "/api/auth/login"
               for s in schemes.values())
