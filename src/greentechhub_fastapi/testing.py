"""testing — a pytest plugin of HTTP fixtures for a service's own tests, on
top of greentechhub-core's database fixtures (greentechhub_core.testing.
sqlalchemy), behind the optional `[testing]` extra. Nothing loads on
install: a service opts in from its conftest.

    # conftest.py
    pytest_plugins = ["greentechhub_fastapi.testing"]

    @pytest.fixture
    def gth_app():
        return app                        # the service's FastAPI app

    @pytest.fixture
    def gth_db():
        return db                         # optional: its core Database

    @pytest.fixture
    def gth_create_user():
        async def create(user_id, password): ...
        return create                     # for client_as

    async def test_page(gth_client, client_as):
        await gth_client.get("/health")
        alice = await client_as("alice")  # signed in through the web form
        assert (await alice.get("/")).status_code == 200

Fixtures:
    gth_app: the app under test. Override it; the default fails with a hint.
    gth_db: the service's greentechhub_core.sqlalchemy Database, or None (the
        default). When set, every session the app opens (its get_session,
        its settings and grant stores, its readiness check) joins the test's
        rolled-back transaction (core's gth_database).
    gth_create_user: an (async) callable(user_id, password) that creates a
        user, for client_as. Override it; the default fails with a hint.
    gth_client: an httpx.AsyncClient on the app (ASGITransport, so the
        lifespan doesn't run: no startup migrations). The app's
        dependency_overrides are restored afterwards, not cleared, so
        register_auth's adapter survives every test.
    client_as: `await client_as(user_id, password=...)` creates the user with
        gth_create_user, signs in through the web form and returns its own
        signed-in client.

Helpers (plain functions, for tests that build their own clients):
    post_login, web_login and hx_triggers.

Needs pytest-asyncio, httpx and core's `[testing]` extra: the `[testing]` extra.
"""

import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

try:
    import httpx
    import pytest
    import pytest_asyncio
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "greentechhub_fastapi.testing needs pytest-asyncio and httpx: "
        "pip install 'greentechhub-fastapi[testing]'"
    ) from exc

from fastapi import FastAPI

from greentechhub_fastapi.auth.cookies import SESSION_COOKIE_NAME
from greentechhub_fastapi.auth.csrf import CSRF_COOKIE_NAME, CSRF_FIELD

pytest_plugins = ["greentechhub_core.testing.sqlalchemy"]

BASE_URL = "http://test"
DEFAULT_PASSWORD = "correct-horse-battery"


# helpers


def hx_triggers(response: httpx.Response) -> dict[str, Any]:
    """The parsed HX-Trigger header of a response (KeyError without one)."""
    return json.loads(response.headers["HX-Trigger"])


def _keep(client: httpx.AsyncClient, response: httpx.Response, name: str) -> str | None:
    # The session and CSRF cookies are Secure, so httpx's jar won't send them
    # back over a http:// base URL; set them again without the flag.
    value = response.cookies.get(name)
    if value is not None:
        client.cookies.set(name, value)
    return value


async def post_login(
    client: httpx.AsyncClient,
    user_id: str,
    password: str,
    *,
    login_url: str = "/login",
    **kwargs: Any,
) -> httpx.Response:
    """POST the sign-in form as a browser would: GET `login_url` first for the
    gth_csrf cookie, then send it back with the same token as the form's
    csrf_token field (a LoginViews without csrf ignores it). kwargs go to
    client.post."""
    page = await client.get(login_url, headers={"Accept": "text/html"})
    token = _keep(client, page, CSRF_COOKIE_NAME) or client.cookies.get(CSRF_COOKIE_NAME) or ""
    data = {"user_id": user_id, "password": password, CSRF_FIELD: token}
    return await client.post(login_url, data=data, **kwargs)


async def web_login(
    client: httpx.AsyncClient, user_id: str, password: str, *, login_url: str = "/login"
) -> None:
    """Sign in through the web form and keep the gth_session cookie on
    `client`; calling it again for another user switches the client to them.
    Fails the test unless the form redirects (303)."""
    response = await post_login(client, user_id, password, login_url=login_url,
                                follow_redirects=False)
    assert response.status_code == 303, f"sign-in as {user_id!r} failed: {response.text}"
    _keep(client, response, SESSION_COOKIE_NAME)


# fixtures


@pytest.fixture
def gth_app() -> FastAPI:
    raise pytest.UsageError(
        "greentechhub_fastapi.testing: override the gth_app fixture to return your FastAPI app"
    )


@pytest.fixture
def gth_db() -> Any:
    return None


@pytest.fixture
def gth_create_user() -> Callable[[str, str], Any]:
    raise pytest.UsageError(
        "greentechhub_fastapi.testing: override the gth_create_user fixture "
        "(an (async) callable(user_id, password)) to use client_as"
    )


@pytest.fixture
def _gth_wired_app(
    gth_app: FastAPI, gth_db: Any, request: pytest.FixtureRequest
) -> Iterator[FastAPI]:
    overrides = dict(gth_app.dependency_overrides)
    try:
        if gth_db is None:
            yield gth_app
        else:
            with request.getfixturevalue("gth_database")(gth_db):
                yield gth_app
    finally:
        gth_app.dependency_overrides.clear()
        gth_app.dependency_overrides.update(overrides)


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


@pytest_asyncio.fixture
async def gth_client(_gth_wired_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(_gth_wired_app) as client:
        yield client


@pytest_asyncio.fixture
async def client_as(
    _gth_wired_app: FastAPI, gth_create_user: Callable[[str, str], Any]
) -> AsyncIterator[Callable[..., Awaitable[httpx.AsyncClient]]]:
    clients: list[httpx.AsyncClient] = []

    async def sign_in(user_id: str, password: str = DEFAULT_PASSWORD, *,
                      login_url: str = "/login") -> httpx.AsyncClient:
        created = gth_create_user(user_id, password)
        if inspect.isawaitable(created):
            await created
        client = _client(_gth_wired_app)
        clients.append(client)
        await web_login(client, user_id, password, login_url=login_url)
        return client

    try:
        yield sign_in
    finally:
        for client in clients:
            await client.aclose()
