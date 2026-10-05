"""verify — optional email verification for the "local" auth adapter,
alongside PasswordResetViews (reset.py).

A service calls `send_link(request, subject, address)` wherever it sets an
address (its own sign-up, a profile save); the person opens the emailed
single-use link (greentechhub-core's OneTimeTokens) and the address counts
as confirmed. Storing that is the service's, so it's the abstract
`mark_verified`, plus `find_unverified` for the "send it again" form.
LoginViews.refuse_sign_in can then turn away anyone not yet confirmed.

The resend form answers the same whether or not an account matched, and a
mail problem there is logged rather than shown, as with password reset.
"""

import logging
import math
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import (
    EmailDeliveryError,
    EmailMessage,
    EmailNotConfiguredError,
    new_email,
)
from greentechhub_core.security import LoginThrottle, OneTimeTokens, account_key, client_key

from greentechhub_fastapi.email import absolute_url, send_email

logger = logging.getLogger(__name__)


class EmailVerificationViews(ABC):
    """Subclass and implement `mark_verified()` and `find_unverified()`, then
    mount `.router()`; call `send_link()` wherever an address is set. Needs
    register_email (with `base_url`, so the link is absolute).

    GET `{verify_url}/{token}`: uses the link up and calls mark_verified.
    The template gets {"login_url"} plus {"done": True}, or
    {"invalid": True, "resend_url"} with status 400 for an unknown, expired
    or used link. The link is used on GET so a click is enough; a mail
    scanner that prefetches it only confirms the address the person gave.

    GET/POST `{verify_url}/resend`: a user ID or email; a matching account
    that still needs confirming gets a new link. The template gets
    {"resend_url", "login_url"}, plus {"sent": True, "identifier"} after a
    request, or {"errors"} (422) for an empty one. Issuing a link revokes the
    earlier ones.

    Pass `throttle` (core's LoginThrottle) to cap the resend emails per
    account and per client; a capped request is answered 429 with
    Retry-After, before any email.
    """

    PURPOSE = "email_verification"

    #: Template names; they default to greentechhub-ui's verification pages.
    verify_template: str = "verify_email_page.html"
    resend_template: str = "verify_email_resend_page.html"

    #: The links' prefix; the resend form is at `{verify_url}/resend`.
    verify_url: str = "/verify-email"

    #: The sign-in page, linked from both pages.
    login_url: str = "/login"

    #: How long an emailed link works.
    token_lifetime: timedelta = timedelta(days=2)

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

    @property
    def resend_url(self) -> str:
        return f"{self.verify_url}/resend"

    @abstractmethod
    async def mark_verified(self, subject: str) -> None:
        """Record that `subject` confirmed their address."""
        ...

    @abstractmethod
    async def find_unverified(self, identifier: str) -> tuple[str, str] | None:
        """The (subject, email address) of the account `identifier` names (a
        user ID or an email, already stripped) while it still needs
        confirming, else None."""
        ...

    def verify_email(self, address: str, link: str) -> EmailMessage:
        """The email that carries the link. Override for your own wording."""
        hours = max(1, int(self.token_lifetime.total_seconds() // 3600))
        text = (
            f"To confirm this email address, open this link within {hours} hours:\n\n{link}\n\n"
            "If you didn't ask for this, ignore this email."
        )
        return new_email(address, "Confirm your email address", text)

    async def send_link(self, request_or_app: Any, subject: str, address: str) -> None:
        """Email `address` a link that confirms it for `subject`. Mail errors
        (core's EmailDeliveryError / EmailNotConfiguredError) propagate."""
        app = getattr(request_or_app, "app", request_or_app)
        token = await self._tokens.issue(subject, self.PURPOSE, lifetime=self.token_lifetime)
        link = absolute_url(app, f"{self.verify_url}/{token}")
        await send_email(app, self.verify_email(address, link))

    def client_address(self, request: Request) -> str | None:
        """The address the throttle counts a client by, as LoginViews'."""
        return request.client.host if request.client else None

    def router(self) -> APIRouter:
        router = APIRouter()
        # The resend routes come first, so "resend" is never taken for a token.
        router.add_api_route(self.resend_url, self._resend_form, methods=["GET"])
        router.add_api_route(self.resend_url, self._resend_submit, methods=["POST"])
        router.add_api_route(f"{self.verify_url}/{{token}}", self._verify, methods=["GET"])
        return router

    # the link

    async def _verify(self, request: Request, token: str):
        subject = await self._tokens.redeem(token, self.PURPOSE)
        if subject is None:
            return self._templates.TemplateResponse(
                request, self.verify_template,
                {"login_url": self.login_url, "invalid": True, "resend_url": self.resend_url},
                status_code=400,
            )
        await self.mark_verified(subject)
        return self._templates.TemplateResponse(
            request, self.verify_template, {"login_url": self.login_url, "done": True}
        )

    # send it again

    def _resend(self, request: Request, status_code: int = 200, headers=None, **extra):
        context = {"resend_url": self.resend_url, "login_url": self.login_url, **extra}
        return self._templates.TemplateResponse(request, self.resend_template, context,
                                                status_code=status_code, headers=headers)

    async def _resend_form(self, request: Request):
        return self._resend(request)

    async def _resend_submit(self, request: Request, identifier: str = Form("")):
        identifier = identifier.strip()
        if not identifier:
            return self._resend(request, 422,
                                errors={"identifier": ["Enter your user ID or email."]})
        if self._throttle is not None:
            keys = [account_key(identifier)]
            if address := self.client_address(request):
                keys.append(client_key(address))
            status = await self._throttle.check(*keys)
            if status.allowed:
                await self._throttle.record_failure(*keys)
            elif status.retry_after is not None:
                seconds = max(1, math.ceil(status.retry_after.total_seconds()))
                minutes = math.ceil(seconds / 60)
                error = (f"Too many requests. Try again in {minutes} "
                         f"minute{'' if minutes == 1 else 's'}.")
                return self._resend(request, 429, {"Retry-After": str(seconds)},
                                    errors={"identifier": [error]}, identifier=identifier)
        account = await self.find_unverified(identifier)
        if account is not None:
            subject, address = account
            try:
                await self.send_link(request, subject, address)
            except (EmailDeliveryError, EmailNotConfiguredError, RuntimeError, ValueError) as exc:
                logger.warning("verification email for %s not sent: %s", subject, exc)
        return self._resend(request, sent=True, identifier=identifier)
