"""require_cookie_csrf: on an API router, a request the session cookie signs in
needs the CSRF token like require_csrf; one with a bearer token the app
resolves doesn't, and neither does an anonymous one."""

import asyncio

import httpx
from fastapi import APIRouter, Depends, FastAPI
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi import register_auth, register_csrf
from greentechhub_fastapi.auth import issue_token
from greentechhub_fastapi.auth.csrf import CSRF_COOKIE_NAME, CSRF_REFUSED, require_cookie_csrf
from greentechhub_fastapi.auth.dependency import get_current_user

TOKEN = "t" * 32
ALICE = Identity(subject="alice", username="alice", email=None, groups=[], claims={})


def _app(settings, *, bearer=True) -> FastAPI:
    app = FastAPI()
    register_auth(app, settings, bearer=bearer)
    register_csrf(app)
    api = APIRouter(prefix="/api", dependencies=[Depends(require_cookie_csrf)])

    @api.get("/things")
    async def list_things(user: Identity | None = Depends(get_current_user)):
        return {"as": user.subject if user else None}

    @api.post("/things")
    async def add_thing(user: Identity | None = Depends(get_current_user)):
        return {"as": user.subject if user else None}

    @api.post("/auth/login")
    async def login():
        return {"access_token": "…"}

    app.include_router(api)
    return app


def _session():
    return DevelopmentIdentityProvider(secret_key="test-secret").issue(ALICE)


def _call(app, method, path, *, cookies=None, headers=None, data=None):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test",
                                     cookies=cookies or {}) as client:
            return await client.request(method, path, headers=headers or {}, data=data)

    return asyncio.run(go())


def test_a_cookie_post_needs_the_token(settings):
    app = _app(settings)
    refused = _call(app, "POST", "/api/things", cookies={"gth_session": _session()})
    assert refused.status_code == 403 and refused.json()["detail"] == CSRF_REFUSED

    cookies = {"gth_session": _session(), CSRF_COOKIE_NAME: TOKEN}
    by_header = _call(app, "POST", "/api/things", cookies=cookies, headers={"X-CSRF-Token": TOKEN})
    assert by_header.status_code == 200 and by_header.json() == {"as": "alice"}
    by_field = _call(app, "POST", "/api/things", cookies=cookies, data={"csrf_token": TOKEN})
    assert by_field.status_code == 200
    wrong = _call(app, "POST", "/api/things", cookies=cookies, headers={"X-CSRF-Token": "x" * 32})
    assert wrong.status_code == 403


def test_a_bearer_post_needs_no_token(settings):
    app = _app(settings)
    bearer = {"Authorization": f"Bearer {issue_token(app, ALICE)}"}
    assert _call(app, "POST", "/api/things", headers=bearer).json() == {"as": "alice"}
    # The bearer header decides who it is, so a cookie alongside it doesn't matter.
    both = _call(app, "POST", "/api/things", headers=bearer, cookies={"gth_session": _session()})
    assert both.status_code == 200


def test_without_bearer_auth_a_bearer_header_doesnt_skip_the_check(settings):
    app = _app(settings, bearer=False)
    response = _call(app, "POST", "/api/things", headers={"Authorization": "Bearer junk"},
                     cookies={"gth_session": _session()})
    assert response.status_code == 403


def test_an_anonymous_post_has_nothing_to_check(settings):
    app = _app(settings)
    assert _call(app, "POST", "/api/auth/login", data={"username": "alice"}).status_code == 200
    assert _call(app, "POST", "/api/things").json() == {"as": None}


def test_safe_methods_pass(settings):
    response = _call(_app(settings), "GET", "/api/things", cookies={"gth_session": _session()})
    assert response.status_code == 200 and response.json() == {"as": "alice"}
