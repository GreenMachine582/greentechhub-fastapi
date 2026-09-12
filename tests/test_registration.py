import asyncio
import logging

import httpx
import pytest
from fastapi import Depends, FastAPI
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi import register_auth, register_core, register_health, register_logging
from greentechhub_fastapi.auth import get_current_user
from tests.conftest import build_app


async def _get(app, path, headers=None, client_addr=("127.0.0.1", 123)):
    transport = httpx.ASGITransport(app=app, client=client_addr)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def test_register_logging_is_idempotent_across_repeated_registration(settings, capsys):
    app = FastAPI()
    register_logging(app, settings)
    register_logging(app, settings)
    logging.getLogger("gth.test.registration").info("only once")

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1


def test_full_reference_app_responds_on_all_registered_surfaces(settings):
    app = build_app(settings)
    response = asyncio.run(_get(app, "/health"))

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Response-Time"].endswith("ms")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_cors_allowed_origins_empty_by_default_blocks_cross_origin(settings):
    app = build_app(settings)
    response = asyncio.run(
        _get(app, "/health", headers={"Origin": "https://not-allowed.example"})
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_allowed_origins_configured_allows_listed_origin(settings):
    settings.CORS_ALLOWED_ORIGINS = "https://allowed.example"
    app = FastAPI()
    register_core(app, settings)
    register_health(app)

    response = asyncio.run(
        _get(app, "/health", headers={"Origin": "https://allowed.example"})
    )
    assert response.headers["access-control-allow-origin"] == "https://allowed.example"


def _add_whoami_route(app):
    @app.get("/whoami")
    async def whoami(user=Depends(get_current_user)):
        return {"username": user.username if user else None}

    return app


async def _get_with_cookies(app, path, cookies=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(path)


def test_register_auth_default_adapter_is_local(settings):
    app = _add_whoami_route(FastAPI())
    register_auth(app, settings)

    identity = Identity(
        subject="user-1", username="alice", email=None, groups=[], claims={}
    )
    provider = DevelopmentIdentityProvider(secret_key=settings.secret_key)
    token = provider.issue(identity)

    response = asyncio.run(_get_with_cookies(app, "/whoami", cookies={"gth_session": token}))
    assert response.json() == {"username": "alice"}


def test_register_auth_empty_auth_adapter_behaves_as_local(settings):
    settings.AUTH_ADAPTER = ""
    app = _add_whoami_route(FastAPI())
    register_auth(app, settings)

    response = asyncio.run(_get_with_cookies(app, "/whoami"))
    assert response.json() == {"username": None}


def test_register_auth_forward_auth_trusted_proxy_resolves_identity(settings):
    settings.AUTH_ADAPTER = "forward_auth"
    settings.TRUSTED_PROXIES = "10.0.0.1"
    app = _add_whoami_route(FastAPI())
    register_core(app, settings)
    register_auth(app, settings)

    response = asyncio.run(
        _get(
            app,
            "/whoami",
            headers={"X-authentik-username": "alice"},
            client_addr=("10.0.0.1", 12345),
        )
    )
    assert response.json() == {"username": "alice"}


def test_register_auth_forward_auth_untrusted_remote_addr_resolves_none(settings):
    settings.AUTH_ADAPTER = "forward_auth"
    settings.TRUSTED_PROXIES = "10.0.0.1"
    app = _add_whoami_route(FastAPI())
    register_core(app, settings)
    register_auth(app, settings)

    response = asyncio.run(
        _get(
            app,
            "/whoami",
            headers={"X-authentik-username": "alice"},
            client_addr=("203.0.113.5", 12345),
        )
    )
    assert response.json() == {"username": None}


def test_register_auth_forward_auth_without_register_core_fails_closed(settings):
    settings.AUTH_ADAPTER = "forward_auth"
    settings.TRUSTED_PROXIES = "10.0.0.1"
    app = _add_whoami_route(FastAPI())
    register_auth(app, settings)

    response = asyncio.run(
        _get(
            app,
            "/whoami",
            headers={"X-authentik-username": "alice"},
            client_addr=("10.0.0.1", 12345),
        )
    )
    assert response.json() == {"username": None}


def test_register_auth_unknown_adapter_raises_value_error(settings):
    settings.AUTH_ADAPTER = "oidc"
    app = FastAPI()

    with pytest.raises(ValueError):
        register_auth(app, settings)
