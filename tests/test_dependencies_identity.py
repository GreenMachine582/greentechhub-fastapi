import asyncio

import httpx
from fastapi import Depends
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi.dependencies import get_current_identity
from tests.conftest import build_app

_IDENTITY = Identity(
    subject="user-1", username="alice", email="alice@example.com", groups=[], claims={}
)


def _add_protected_route(app):
    @app.get("/protected")
    async def protected(identity=Depends(get_current_identity)):
        return {"username": identity.username}

    return app


async def _get(app, cookies=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get("/protected")


def test_authenticated_request_returns_identity(settings):
    app = _add_protected_route(build_app(settings))
    provider = DevelopmentIdentityProvider(secret_key=settings.secret_key)
    token = provider.issue(_IDENTITY)

    response = asyncio.run(_get(app, cookies={"gth_session": token}))
    assert response.status_code == 200
    assert response.json() == {"username": "alice"}


def test_unauthenticated_request_returns_401(settings):
    app = _add_protected_route(build_app(settings))

    response = asyncio.run(_get(app))
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthorized"
    assert body["message"] == "authentication required"
