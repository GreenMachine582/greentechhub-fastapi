import asyncio

import httpx
from fastapi import Depends, FastAPI
from greentechhub_core.identity import AuthentikIdentityProvider

from greentechhub_fastapi.auth.forward_auth import build_forward_auth_get_current_user


class _StateInjectorMiddleware:
    """Stands in for ProxyHeadersMiddleware's trust-flag stamping, without
    depending on real remote-address plumbing — see test_registration.py for
    the end-to-end proof that ProxyHeadersMiddleware and this factory agree."""

    def __init__(self, app, *, trusted):
        self.app = app
        self.trusted = trusted

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope["state"] = {"trusted_proxy": self.trusted}
        await self.app(scope, receive, send)


def _build_app(*, trusted):
    app = FastAPI()
    provider = AuthentikIdentityProvider()
    get_current_user = build_forward_auth_get_current_user(provider)

    @app.get("/whoami")
    async def whoami(user=Depends(get_current_user)):
        return {"username": user.username if user else None}

    if trusted is None:
        return app
    return _StateInjectorMiddleware(app, trusted=trusted)


async def _get(app, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/whoami", headers=headers)


def test_trusted_proxy_with_valid_headers_resolves_identity():
    app = _build_app(trusted=True)
    response = asyncio.run(_get(app, headers={"X-authentik-username": "alice"}))
    assert response.json() == {"username": "alice"}


def test_untrusted_remote_addr_ignores_authentik_headers_even_if_present():
    app = _build_app(trusted=False)
    response = asyncio.run(_get(app, headers={"X-authentik-username": "alice"}))
    assert response.json() == {"username": None}


def test_trusted_proxy_missing_required_header_resolves_none():
    app = _build_app(trusted=True)
    response = asyncio.run(_get(app))
    assert response.json() == {"username": None}


def test_no_state_at_all_fails_closed_without_crashing():
    app = _build_app(trusted=None)
    response = asyncio.run(_get(app, headers={"X-authentik-username": "alice"}))
    assert response.status_code == 200
    assert response.json() == {"username": None}
