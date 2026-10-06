import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI, Form, Request
from greentechhub_core.security import InMemoryAttemptStore, LoginThrottle, account_key, client_key
from greentechhub_core.types import UnauthorizedError

from greentechhub_fastapi.auth import LoginLockedOut, client_address, throttled_login
from greentechhub_fastapi.auth.throttle import lockout_message, retry_after_seconds, throttle_keys
from greentechhub_fastapi.exceptions import register_api_error_handlers, register_exception_handlers


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self):
        return self.now


# ── helpers ─────────────────────────────────────────────────────────────────


def test_throttle_keys_count_the_account_and_a_known_client():
    assert throttle_keys(" Alice", "203.0.113.7") == [account_key("alice"),
                                                      client_key("203.0.113.7")]
    assert throttle_keys("alice", None) == [account_key("alice")]


def test_retry_after_is_whole_seconds_and_at_least_one():
    assert retry_after_seconds(timedelta(seconds=89.2)) == 90
    assert retry_after_seconds(timedelta(0)) == 1


def test_lockout_message_rounds_up_to_minutes():
    assert lockout_message("failed sign-ins", timedelta(minutes=15)) == (
        "Too many failed sign-ins. Try again in 15 minutes.")
    assert lockout_message("requests", timedelta(seconds=30)) == (
        "Too many requests. Try again in 1 minute.")


def test_login_locked_out_is_a_429_with_retry_after():
    locked = LoginLockedOut(timedelta(minutes=2))
    assert locked.status_code == 429
    assert locked.headers == {"Retry-After": "120"}
    assert locked.detail == "Too many failed sign-ins. Try again in 2 minutes."
    assert locked.retry_after == timedelta(minutes=2)


# ── throttled_login on an API token route ───────────────────────────────────


def _api(throttle):
    """A token endpoint the way a service writes one: its own password check,
    throttled_login around it, the envelope from register_api_error_handlers."""
    app = FastAPI()
    register_exception_handlers(app)
    register_api_error_handlers(app, prefix="/api")
    calls = []

    @app.post("/api/token")
    async def token(request: Request, username: str = Form(...), password: str = Form(...)):
        async def check():
            calls.append(username)
            return username if password == "s3cret" else None

        user = await throttled_login(throttle, username, check,
                                     address=client_address(request))
        if user is None:
            raise UnauthorizedError("Incorrect user ID or password")
        return {"access_token": f"token-for-{user}"}

    return app, calls


def _post(app, password, username="alice", client=("203.0.113.7", 1234)):
    async def run():
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.post("/api/token", data={"username": username, "password": password})

    return asyncio.run(run())


def _throttle(clock=None):
    return LoginThrottle(InMemoryAttemptStore(), max_failures=3, clock=clock or _Clock())


def test_failures_below_the_limit_are_the_routes_own_401():
    app, _ = _api(_throttle())
    response = _post(app, "wrong")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_the_failure_that_reaches_the_limit_answers_429_in_the_envelope():
    app, _ = _api(_throttle())
    assert [_post(app, "wrong").status_code for _ in range(2)] == [401, 401]
    response = _post(app, "wrong")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "900"
    assert response.json() == {"code": "too_many_requests", "details": None,
                               "message": "Too many failed sign-ins. Try again in 15 minutes."}


def test_while_locked_the_password_isnt_checked():
    app, calls = _api(_throttle())
    for _ in range(3):
        _post(app, "wrong")
    calls.clear()
    assert _post(app, "s3cret").status_code == 429
    assert calls == []


def test_the_lock_ends_after_the_lockout():
    clock = _Clock()
    app, _ = _api(_throttle(clock))
    for _ in range(3):
        _post(app, "wrong")
    clock.now += timedelta(minutes=16)
    assert _post(app, "s3cret").json() == {"access_token": "token-for-alice"}


def test_success_clears_the_account_but_not_the_client():
    throttle = _throttle()
    app, _ = _api(throttle)
    for _ in range(2):
        _post(app, "wrong")
    assert _post(app, "s3cret").status_code == 200
    assert asyncio.run(throttle.check(account_key("alice"))).failures == 0
    assert asyncio.run(throttle.check(client_key("203.0.113.7"))).failures == 2


def test_one_client_guessing_many_accounts_is_locked_out():
    app, _ = _api(_throttle())
    statuses = [_post(app, "wrong", username=f"user-{n}").status_code for n in range(3)]
    assert statuses == [401, 401, 429]
    # Another client can still try those accounts.
    assert _post(app, "wrong", username="user-0", client=("198.51.100.1", 1)).status_code == 401


def test_without_a_throttle_it_just_authenticates():
    app, _ = _api(None)
    assert [_post(app, "wrong").status_code for _ in range(5)] == [401] * 5
    assert _post(app, "s3cret").status_code == 200


def test_no_client_address_counts_by_account_only():
    throttle = _throttle()

    async def run():
        async def check():
            return None

        for _ in range(2):
            assert await throttled_login(throttle, "alice", check, address=None) is None
        return await throttle.check(account_key("alice"))

    assert asyncio.run(run()).failures == 2
