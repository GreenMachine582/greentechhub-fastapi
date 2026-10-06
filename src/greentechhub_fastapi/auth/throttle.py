"""throttle — the HTTP side of core's LoginThrottle: the keys a request is
counted by, the 429 lockout answer, and `throttled_login`, the
check → authenticate → record flow LoginViews runs.

LoginViews, PasswordResetViews and EmailVerificationViews use these
helpers; a service's own login route outside them (e.g. an OAuth2 token
endpoint for its API) calls `throttled_login` to get the same lockout,
sharing one LoginThrottle with its sign-in page so a guesser locked out of
one can't carry on at the other.
"""

import math
from collections.abc import Awaitable, Callable
from datetime import timedelta

from fastapi import HTTPException, Request
from greentechhub_core.security import LoginThrottle, account_key, client_key


def client_address(request: Request) -> str | None:
    """The address a throttle counts a client by: the request's client host,
    which register_core's ProxyHeadersMiddleware has already corrected when
    the service sits behind a trusted proxy (TRUSTED_PROXIES)."""
    return request.client.host if request.client else None


def throttle_keys(identifier: str, address: str | None) -> list[str]:
    """The keys one attempt counts against: the account, plus the client
    when its address is known."""
    keys = [account_key(identifier)]
    if address:
        keys.append(client_key(address))
    return keys


def retry_after_seconds(retry_after: timedelta) -> int:
    """`retry_after` as a Retry-After header value: whole seconds, at least 1."""
    return max(1, math.ceil(retry_after.total_seconds()))


def lockout_message(what: str, retry_after: timedelta) -> str:
    """e.g. "Too many failed sign-ins. Try again in 15 minutes." for
    what="failed sign-ins"."""
    minutes = math.ceil(retry_after_seconds(retry_after) / 60)
    return f"Too many {what}. Try again in {minutes} minute{'' if minutes == 1 else 's'}."


class LoginLockedOut(HTTPException):
    """429 with Retry-After and the lockout message as its detail, raised by
    `throttled_login`. Under register_api_error_handlers' prefix it is
    answered in the {code, message} envelope (code "too_many_requests");
    a page catches it and renders its own 429 instead, as LoginViews does."""

    def __init__(self, retry_after: timedelta) -> None:
        super().__init__(
            429,
            detail=lockout_message("failed sign-ins", retry_after),
            headers={"Retry-After": str(retry_after_seconds(retry_after))},
        )
        self.retry_after = retry_after


async def throttled_login[T](
    throttle: LoginThrottle | None,
    user_id: str,
    authenticate: Callable[[], Awaitable[T | None]],
    *,
    address: str | None,
) -> T | None:
    """Run one login attempt under `throttle`.

    Raises LoginLockedOut, without calling `authenticate`, while the account
    or the client is locked out. Otherwise awaits `authenticate()`: None is a
    failed attempt and counts against both keys (raising LoginLockedOut if it
    trips the lock, else returning None); anything else clears the account's
    count (not the client's: one good login mustn't wipe a guesser's) and is
    returned. With `throttle` None it just returns `authenticate()`.

    Args:
        throttle: the shared LoginThrottle, or None to throttle nothing.
        user_id: what the person typed as their user ID.
        authenticate: checks the password; the identity/user, or None.
        address: the client's address (`client_address(request)`), or None
            to count by account only.
    """
    if throttle is None:
        return await authenticate()
    keys = throttle_keys(user_id, address)
    status = await throttle.check(*keys)
    if not status.allowed and status.retry_after is not None:
        raise LoginLockedOut(status.retry_after)
    result = await authenticate()
    if result is None:
        status = await throttle.record_failure(*keys)
        if not status.allowed and status.retry_after is not None:
            raise LoginLockedOut(status.retry_after)
        return None
    await throttle.record_success(account_key(user_id))
    return result
