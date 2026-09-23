import asyncio

import httpx
from fastapi import Depends
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi.dependencies import require_page_identity
from tests.conftest import build_app

_IDENTITY = Identity(
    subject="user-1", username="alice", email="alice@example.com", groups=[], claims={}
)


def _add_page_route(app, **kwargs):
    page_identity = require_page_identity(**kwargs)

    @app.get("/page")
    async def page(identity=Depends(page_identity)):
        return {"username": identity.username}

    return app


async def _get(app, headers=None, cookies=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get("/page", headers=headers, follow_redirects=False)


def test_authenticated_request_passes_identity_through(settings):
    app = _add_page_route(build_app(settings))
    token = DevelopmentIdentityProvider(secret_key=settings.secret_key).issue(_IDENTITY)

    response = asyncio.run(_get(app, cookies={"gth_session": token}))
    assert response.status_code == 200
    assert response.json() == {"username": "alice"}


def test_anonymous_page_request_redirects_to_login(settings):
    app = _add_page_route(build_app(settings))

    response = asyncio.run(_get(app))
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "hx-redirect" not in response.headers


def test_anonymous_htmx_request_gets_hx_redirect_not_a_303(settings):
    app = _add_page_route(build_app(settings))

    response = asyncio.run(_get(app, headers={"HX-Request": "true"}))
    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"
    assert "location" not in response.headers


def test_login_url_is_configurable(settings):
    app = _add_page_route(build_app(settings), login_url="/accounts/login")

    assert asyncio.run(_get(app)).headers["location"] == "/accounts/login"
    htmx = asyncio.run(_get(app, headers={"HX-Request": "true"}))
    assert htmx.headers["hx-redirect"] == "/accounts/login"
