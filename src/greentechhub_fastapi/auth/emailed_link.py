"""emailed_link — what PasswordResetViews and EmailVerificationViews share:
the setup (templates, single-use tokens, an optional throttle), emailing a
single-use link, and the "enter your user ID or email" form that sends one.

That form answers the same whether or not an account matched, counts every
request against the throttle, and logs a mail problem rather than showing
it, so the page never tells anyone which accounts exist.
"""

import logging
from abc import ABC
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import EmailMessage
from greentechhub_core.security import (
    LoginThrottle,
    OneTimeTokens,
    lockout_message,
    throttle_keys,
)

from greentechhub_fastapi.auth.csrf import CSRF_REFUSED, CsrfProtected
from greentechhub_fastapi.auth.throttle import client_address
from greentechhub_fastapi.email import EMAIL_SEND_ERRORS, absolute_url, send_email

#: The identifier form's "nothing entered" message.
ENTER_IDENTIFIER = "Enter your user ID or email."


class EmailedLinkViews(CsrfProtected, ABC):
    """The shared base: subclasses set PURPOSE (the token purpose),
    token_lifetime and their own pages and routes."""

    PURPOSE: str

    #: The sign-in page, linked from the pages.
    login_url: str = "/login"

    #: How long an emailed link works.
    token_lifetime: timedelta

    def __init__(
        self,
        *,
        templates: Jinja2Templates,
        tokens: OneTimeTokens,
        throttle: LoginThrottle | None = None,
    ) -> None:
        self._templates = templates
        self._tokens = tokens
        self._throttle = throttle

    def client_address(self, request: Request) -> str | None:
        """The address the throttle counts a client by, as LoginViews'."""
        return client_address(request)

    async def _email_link(
        self,
        request_or_app: Any,
        subject: str,
        address: str,
        url_prefix: str,
        make_email: Callable[[str, str], EmailMessage],
    ) -> None:
        """Issue a single-use token for `subject` and email `address` the
        link `{url_prefix}/{token}` (absolute, via register_email's
        base_url). Mail errors propagate."""
        app = getattr(request_or_app, "app", request_or_app)
        token = await self._tokens.issue(subject, self.PURPOSE, lifetime=self.token_lifetime)
        link = absolute_url(app, f"{url_prefix}/{token}")
        await send_email(app, make_email(address, link))

    async def _identifier_submit(
        self,
        request: Request,
        identifier: str,
        csrf_token: str,
        *,
        render: Callable[..., Response],
        find: Callable[[str], Awaitable[tuple[str, str] | None]],
        send: Callable[[Request, str, str], Awaitable[None]],
        lockout_what: str,
        log: logging.Logger,
        log_what: str,
    ) -> Response:
        """The identifier form's POST: refuse a bad CSRF token (403) or an
        empty identifier (422); count the request, and answer 429 with
        Retry-After when the throttle says so; else email the account
        `find` returns (if any), logging a mail problem on `log`, and show
        the same "sent" page either way."""
        identifier = identifier.strip()
        if self._csrf_refused(request, csrf_token):
            return render(request, 403, errors={"identifier": [CSRF_REFUSED]},
                          identifier=identifier)
        if not identifier:
            return render(request, 422, errors={"identifier": [ENTER_IDENTIFIER]})
        if self._throttle is not None:
            keys = throttle_keys(identifier, self.client_address(request))
            status = await self._throttle.check(*keys)
            if status.allowed:
                await self._throttle.record_failure(*keys)
            elif status.retry_after is not None:
                error = lockout_message(lockout_what, status.retry_after)
                headers = {"Retry-After": str(status.retry_after_seconds)}
                return render(request, 429, headers, errors={"identifier": [error]},
                              identifier=identifier)
        account = await find(identifier)
        if account is not None:
            subject, address = account
            try:
                await send(request, subject, address)
            except EMAIL_SEND_ERRORS as exc:
                log.warning("%s for %s not sent: %s", log_what, subject, exc)
        return render(request, sent=True, identifier=identifier)
