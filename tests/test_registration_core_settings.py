"""The adapter settings come with greentechhub-core's GTHBaseSettings (core
v0.12): a service's Settings that declares none of them still has
TRUSTED_PROXIES, CORS_ALLOWED_ORIGINS, AUTH_ADAPTER and ROLE_* honoured.
SCREAMING_CASE attributes (declared, or set at runtime) keep working."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from greentechhub_core.config import GTHBaseSettings

from greentechhub_fastapi import register_core
from greentechhub_fastapi.registration._settings import (
    read_list_setting,
    read_str_setting,
    setting_value,
)
from greentechhub_fastapi.registration.permissions import read_role_map

ADAPTER_VARS = ["AUTH_ADAPTER", "CORS_ALLOWED_ORIGINS", "TRUSTED_PROXIES", "ROLE_GROUPS",
                "ROLE_BOOTSTRAP"]


class _BareSettings(GTHBaseSettings):
    """A service's Settings that declares none of the adapter settings."""


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    for name in ADAPTER_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_env_vars_reach_the_readers_through_gthbasesettings(env):
    env.setenv("TRUSTED_PROXIES", "10.0.0.1, 10.0.0.2")
    env.setenv("AUTH_ADAPTER", "forward_auth")
    env.setenv("ROLE_BOOTSTRAP", "alice=admin|editor")
    settings = _BareSettings(_env_file=None)
    assert read_list_setting(settings, "TRUSTED_PROXIES") == ["10.0.0.1", "10.0.0.2"]
    assert read_str_setting(settings, "AUTH_ADAPTER", "local") == "forward_auth"
    assert read_role_map(settings, "ROLE_BOOTSTRAP") == {"alice": ["admin", "editor"]}
    assert read_role_map(settings, "ROLE_GROUPS") == {}


def test_register_core_trusts_the_proxy_from_gthbasesettings(env):
    env.setenv("TRUSTED_PROXIES", "10.0.0.5")
    app = FastAPI()
    register_core(app, _BareSettings(_env_file=None))

    @app.get("/whoami")
    async def whoami(request: Request):
        return request.client.host if request.client else None

    async def seen(peer):
        transport = httpx.ASGITransport(app=app, client=(peer, 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return (await c.get("/whoami", headers={"X-Forwarded-For": "203.0.113.9"})).json()

    assert asyncio.run(seen("10.0.0.5")) == "203.0.113.9"
    assert asyncio.run(seen("198.51.100.7")) == "198.51.100.7"


def test_register_core_cors_from_gthbasesettings(env):
    env.setenv("CORS_ALLOWED_ORIGINS", "https://allowed.example")
    app = FastAPI()
    register_core(app, _BareSettings(_env_file=None))

    @app.get("/ping")
    async def ping():
        return "pong"

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.get("/ping", headers={"Origin": "https://allowed.example"})

    response = asyncio.run(run())
    assert response.headers["access-control-allow-origin"] == "https://allowed.example"


def test_safe_defaults_without_env(env):
    settings = _BareSettings(_env_file=None)
    assert read_list_setting(settings, "TRUSTED_PROXIES") == []
    assert read_list_setting(settings, "CORS_ALLOWED_ORIGINS") == []
    assert read_str_setting(settings, "AUTH_ADAPTER", "local") == "local"


def test_a_screaming_case_attribute_set_at_runtime_still_counts():
    # e.g. PyFinBot sets CORS_ALLOWED_ORIGINS = "*" in development
    settings = SimpleNamespace(cors_allowed_origins="", CORS_ALLOWED_ORIGINS="*")
    assert read_list_setting(settings, "CORS_ALLOWED_ORIGINS") == ["*"]


def test_an_object_without_gthbasesettings_still_works():
    settings = SimpleNamespace(TRUSTED_PROXIES="10.0.0.1")
    assert read_list_setting(settings, "TRUSTED_PROXIES") == ["10.0.0.1"]


def test_the_services_own_attribute_wins_over_cores_default():
    # core's auth_adapter defaults to "local"; a service that set AUTH_ADAPTER
    # itself must not be overridden by it.
    settings = SimpleNamespace(auth_adapter="local", AUTH_ADAPTER="forward_auth")
    assert setting_value(settings, "AUTH_ADAPTER") == "forward_auth"
    assert setting_value(SimpleNamespace(auth_adapter="local"), "AUTH_ADAPTER") == "local"
    assert setting_value(SimpleNamespace(), "TRUSTED_PROXIES") is None
