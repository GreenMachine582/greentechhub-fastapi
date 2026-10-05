"""reset — optional password-reset route scaffolding for the "local" auth
adapter, alongside LoginViews (views.py) and RegisterViews (register.py).

The flow is the same in every service: a "forgot password" form that emails
a single-use link (greentechhub-core's OneTimeTokens, sent with
register_email's sender), and the link's "choose a new password" form. Only
"find this account" and "store this password" differ, so those are the two
abstract methods, as RegisterViews leaves only create_user().

The forgot form answers the same whether or not an account matched, and a
mail problem is logged rather than shown, so the page never tells anyone
which accounts exist.
"""

import logging
import math
from abc import ABC, abstractmethod
from datetime import timedelta

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


class PasswordResetViews(ABC):
    """Subclass and implement `find_account()` and `set_password()`, then
    mount `.router()`. Needs register_email (with `base_url`, so the
    emailed link is absolute) for the email to go out.

    GET/POST `forgot_url`: the form takes a user ID or email; a matching
    account gets a link to `{reset_url}/{token}`, valid for
    `token_lifetime`. The answer is the same either way: the template gets
    {"forgot_url", "login_url"}, plus {"sent": True, "identifier"} after a
    request, or {"errors"} (422) for an empty one.

    GET/POST `{reset_url}/{token}`: the "choose a new password" form,
    {"action", "login_url", "min_password_length"}, plus {"errors"} (422)
    after a refused password. A valid one is stored and the page shows
    {"done": True}; an unknown, expired or used link shows
    {"invalid": True, "forgot_url"} with status 400. It doesn't sign the
    person in, and sessions already issued stay valid (stateless JWTs).

    Pass `throttle` (core's LoginThrottle) to cap reset emails per account
    and per client: every request counts, and a capped one is answered 429
    with Retry-After, before any email.
    """

    PURPOSE = "password_reset"

    #: Template names, resolved against the Jinja2Templates passed to
    #: __init__; they default to greentechhub-ui's password reset pages.
    forgot_template: str = "forgot_password_page.html"
    reset_template: str = "reset_password_page.html"

    #: Where the forgot form lives, and the prefix of the emailed links.
    forgot_url: str = "/forgot-password"
    reset_url: str = "/reset-password"

    #: The sign-in page, linked from both pages.
    login_url: str = "/login"

    #: The shortest password accepted.
    min_password_length: int = 8

    #: How long an emailed link works.
    token_lifetime: timedelta = timedelta(hours=1)

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

    @abstractmethod
    async def find_account(self, identifier: str) -> tuple[str, str] | None:
        """The (subject, email address) of the account `identifier` names (a
        user ID or an email, already stripped), or None. An account without
        an address can't be reset by email: return None for it."""
        ...

    @abstractmethod
    async def set_password(self, subject: str, password: str) -> None:
        """Store `password` for `subject`; hashing it (core's hash_password)
        is yours. Already checked for length and confirmation."""
        ...

    def reset_email(self, address: str, link: str) -> EmailMessage:
        """The email that carries the link. Override for your own wording."""
        minutes = max(1, int(self.token_lifetime.total_seconds() // 60))
        text = (
            "Someone asked to reset the password for your account. To choose a new one, "
            f"open this link within {minutes} minutes:\n\n{link}\n\n"
            "If it wasn't you, ignore this email: your password stays the same."
        )
        return new_email(address, "Reset your password", text)

    def client_address(self, request: Request) -> str | None:
        """The address the throttle counts a client by, as LoginViews'."""
        return request.client.host if request.client else None

    def router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route(self.forgot_url, self._forgot_form, methods=["GET"])
        router.add_api_route(self.forgot_url, self._forgot_submit, methods=["POST"])
        router.add_api_route(f"{self.reset_url}/{{token}}", self._reset_form, methods=["GET"])
        router.add_api_route(f"{self.reset_url}/{{token}}", self._reset_submit, methods=["POST"])
        return router

    # forgot password

    def _forgot(self, request: Request, status_code: int = 200, headers=None, **extra):
        context = {"forgot_url": self.forgot_url, "login_url": self.login_url, **extra}
        return self._templates.TemplateResponse(request, self.forgot_template, context,
                                                status_code=status_code, headers=headers)

    async def _forgot_form(self, request: Request):
        return self._forgot(request)

    async def _forgot_submit(self, request: Request, identifier: str = Form("")):
        identifier = identifier.strip()
        if not identifier:
            return self._forgot(request, 422,
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
                error = (f"Too many reset requests. Try again in {minutes} "
                         f"minute{'' if minutes == 1 else 's'}.")
                return self._forgot(request, 429, {"Retry-After": str(seconds)},
                                    errors={"identifier": [error]}, identifier=identifier)
        account = await self.find_account(identifier)
        if account is not None:
            await self._email_link(request, *account)
        return self._forgot(request, sent=True, identifier=identifier)

    async def _email_link(self, request: Request, subject: str, address: str) -> None:
        try:
            token = await self._tokens.issue(subject, self.PURPOSE, lifetime=self.token_lifetime)
            link = absolute_url(request.app, f"{self.reset_url}/{token}")
            await send_email(request.app, self.reset_email(address, link))
        except (EmailDeliveryError, EmailNotConfiguredError, RuntimeError, ValueError) as exc:
            logger.warning("password reset email for %s not sent: %s", subject, exc)

    # choose a new password

    def _reset(self, request: Request, token: str, status_code: int = 200, **extra):
        context = {"action": f"{self.reset_url}/{token}", "login_url": self.login_url,
                   "min_password_length": self.min_password_length, **extra}
        return self._templates.TemplateResponse(request, self.reset_template, context,
                                                status_code=status_code)

    def _invalid(self, request: Request, token: str):
        return self._reset(request, token, 400, invalid=True, forgot_url=self.forgot_url)

    async def _reset_form(self, request: Request, token: str):
        if await self._tokens.peek(token, self.PURPOSE) is None:
            return self._invalid(request, token)
        return self._reset(request, token)

    async def _reset_submit(
        self,
        request: Request,
        token: str,
        password: str = Form(""),
        password_confirm: str = Form(""),
    ):
        errors: dict[str, list[str]] = {}
        if len(password) < self.min_password_length:
            errors["password"] = [f"Use at least {self.min_password_length} characters."]
        elif password != password_confirm:
            errors["password_confirm"] = ["The passwords don't match."]
        if errors:
            if await self._tokens.peek(token, self.PURPOSE) is None:
                return self._invalid(request, token)
            return self._reset(request, token, 422, errors=errors)
        subject = await self._tokens.redeem(token, self.PURPOSE)
        if subject is None:
            return self._invalid(request, token)
        await self.set_password(subject, password)
        if self._throttle is not None:
            await self._throttle.record_success(account_key(subject))
        return self._reset(request, token, done=True)
