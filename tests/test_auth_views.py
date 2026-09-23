import asyncio

import httpx
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from jinja2 import DictLoader, Environment

from greentechhub_fastapi.auth.views import LoginViews

_USERS = {
    "alice": (
        "s3cret",
        Identity(subject="user-1", username="alice", email=None, groups=[], claims={}),
    ),
}


def _make_templates() -> Jinja2Templates:
    env = Environment(
        loader=DictLoader({"login.html": "Log in{% if error %} - {{ error }}{% endif %}"})
    )
    return Jinja2Templates(env=env)


class _FakeLoginViews(LoginViews):
    async def authenticate(self, user_id, password):
        entry = _USERS.get(user_id)
        if entry and entry[0] == password:
            return entry[1]
        return None


def _build_app(**overrides):
    app = FastAPI()
    provider = DevelopmentIdentityProvider(secret_key="secret-a")
    views = _FakeLoginViews(templates=_make_templates(), identity_provider=provider)
    for key, value in overrides.items():
        setattr(views, key, value)
    app.include_router(views.router())
    return app


async def _get(app, path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def _post(app, path, data=None, cookies=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.post(path, data=data or {}, follow_redirects=False)


def test_login_form_renders():
    app = _build_app()
    response = asyncio.run(_get(app, "/login"))
    assert response.status_code == 200
    assert "Log in" in response.text


def test_valid_credentials_set_cookie_and_redirect():
    app = _build_app()
    response = asyncio.run(_post(app, "/login", data={"user_id": "alice", "password": "s3cret"}))
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "gth_session" in response.cookies


def test_invalid_credentials_rerender_with_error():
    app = _build_app()
    response = asyncio.run(_post(app, "/login", data={"user_id": "alice", "password": "wrong"}))
    assert response.status_code == 401
    assert "Incorrect user ID or password" in response.text


def test_unknown_user_rerenders_with_error():
    app = _build_app()
    response = asyncio.run(_post(app, "/login", data={"user_id": "nobody", "password": "wrong"}))
    assert response.status_code == 401
    assert "Incorrect user ID or password" in response.text


def test_logout_clears_cookie_and_redirects():
    app = _build_app()
    response = asyncio.run(_post(app, "/logout", cookies={"gth_session": "some-token"}))
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert response.cookies.get("gth_session") is None


def test_custom_redirect_and_login_url_are_respected():
    app = _build_app(redirect_url="/dashboard", login_url="/auth/login")

    form_response = asyncio.run(_get(app, "/auth/login"))
    assert form_response.status_code == 200

    login_response = asyncio.run(
        _post(app, "/auth/login", data={"user_id": "alice", "password": "s3cret"})
    )
    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/dashboard"

    logout_response = asyncio.run(_post(app, "/logout"))
    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/auth/login"
