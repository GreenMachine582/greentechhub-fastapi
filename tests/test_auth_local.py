import asyncio

import httpx
from fastapi import Depends, FastAPI
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi.auth.local import build_local_get_current_user

_IDENTITY = Identity(
    subject="user-1", username="alice", email="alice@example.com", groups=[], claims={}
)


def _build_app(provider, *, cookie_name="gth_session"):
    app = FastAPI()
    get_current_user = build_local_get_current_user(provider, cookie_name=cookie_name)

    @app.get("/whoami")
    async def whoami(user=Depends(get_current_user)):
        return {"username": user.username if user else None}

    return app


async def _get(app, cookies=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get("/whoami")


def test_valid_cookie_resolves_identity():
    provider = DevelopmentIdentityProvider(secret_key="secret-a")
    token = provider.issue(_IDENTITY)
    app = _build_app(provider)

    response = asyncio.run(_get(app, cookies={"gth_session": token}))
    assert response.json() == {"username": "alice"}


def test_missing_cookie_resolves_none():
    provider = DevelopmentIdentityProvider(secret_key="secret-a")
    app = _build_app(provider)

    response = asyncio.run(_get(app))
    assert response.json() == {"username": None}


def test_token_signed_with_different_secret_resolves_none():
    issuing_provider = DevelopmentIdentityProvider(secret_key="secret-a")
    token = issuing_provider.issue(_IDENTITY)

    verifying_provider = DevelopmentIdentityProvider(secret_key="secret-b")
    app = _build_app(verifying_provider)

    response = asyncio.run(_get(app, cookies={"gth_session": token}))
    assert response.json() == {"username": None}


def test_tampered_token_resolves_none():
    provider = DevelopmentIdentityProvider(secret_key="secret-a")
    token = provider.issue(_IDENTITY)
    app = _build_app(provider)

    response = asyncio.run(_get(app, cookies={"gth_session": token + "tampered"}))
    assert response.json() == {"username": None}


def test_custom_cookie_name_is_respected():
    provider = DevelopmentIdentityProvider(secret_key="secret-a")
    token = provider.issue(_IDENTITY)
    app = _build_app(provider, cookie_name="custom_session")

    response = asyncio.run(_get(app, cookies={"custom_session": token}))
    assert response.json() == {"username": "alice"}

    response = asyncio.run(_get(app, cookies={"gth_session": token}))
    assert response.json() == {"username": None}
