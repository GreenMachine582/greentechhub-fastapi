"""register — optional self-service sign-up route scaffolding for the
"local" auth adapter, the companion to LoginViews (views.py).

Everything around storing a new user is the same in every service: render a
form, check the user ID and the password (length, confirmation), sign the
new user straight in (session JWT via the caller's
DevelopmentIdentityProvider, the cookie, the landing-page redirect). Only
"create this user in my database" differs, so that's the one abstract
method, just as LoginViews leaves only authenticate().

Same rules as LoginViews: no ORM or session here (create_user acquires its
own, e.g. through resolve_dependency), and the caller builds the identity
provider. Whether sign-up is open at all is `is_open(request)`: by default
`signup_open` and, when register_settings registered it, core's
self_signup_setting, so an admin can close sign-up from the settings page.
Override it for another rule, e.g. a feature flag.

With `ask_email` the form also takes an email address, and with a
`verification` (EmailVerificationViews) the new user is emailed a link to
confirm it, optionally before they can sign in.
"""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import EMAIL_INVALID, email_looks_valid
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.security import password_problem

from greentechhub_fastapi.auth.cookies import create_session_cookie
from greentechhub_fastapi.auth.csrf import CSRF_REFUSED, CsrfProtected
from greentechhub_fastapi.auth.errors import FormErrors
from greentechhub_fastapi.email import EMAIL_SEND_ERRORS

if TYPE_CHECKING:
    from greentechhub_fastapi.auth.verify import EmailVerificationViews

logger = logging.getLogger(__name__)


class RegistrationError(FormErrors):
    """Raised by `RegisterViews.create_user` for an expected refusal, e.g. a
    user ID that's taken. `errors` maps form fields ("user_id", "password")
    to their messages; the form is shown again with them, status 422."""


class RegisterViews(CsrfProtected, ABC):
    """Subclass and implement `create_user()`, then mount `.router()`.

    Ships GET/POST `register_url`. A successful sign-up signs the new user in
    and lands them where a login would (the user's landing page when
    register_settings registered core's landing_page_setting, else
    `redirect_url`). While `is_open(request)` is False both routes answer
    404, so a closed sign-up looks like no sign-up at all.

    The template gets {"register_url", "login_url", "min_password_length"},
    plus {"errors", "user_id"} after a refused sign-up — errors as
    {field: [message]}; the user ID is kept, a password never is.

    Email (opt-in): with `ask_email` the form also posts `email` (required
    unless `require_email` is False, and checked for shape), the template
    gets {"ask_email": True} plus the `email` back after a refusal, and
    create_user is called with an `email` keyword. Pass `verification` (an
    EmailVerificationViews) and the new user is emailed a confirmation link;
    a mail problem is logged, not shown. With `sign_in_before_verified`
    False they aren't signed in: the template gets {"verify_sent": True,
    "email", "verify_resend_url"} instead, and the service's
    LoginViews.refuse_sign_in keeps them out until they confirm.
    """

    #: Template name resolved against the Jinja2Templates instance passed to
    #: __init__. Defaults to greentechhub-ui's sign-up page; set your own
    #: template name to keep a custom page.
    register_template: str = "register_page.html"

    #: Where the two sign-up routes are mounted.
    register_url: str = "/register"

    #: The sign-in page, linked from the sign-up page ("Already have an account?").
    login_url: str = "/login"

    #: Where a new user lands — or, with core's landing_page_setting registered,
    #: the fallback when it can't be resolved.
    redirect_url: str = "/"

    #: False closes sign-up whatever the self-signup setting says. Override
    #: is_open() for another per-request answer (a feature flag).
    signup_open: bool = True

    #: The shortest password accepted.
    min_password_length: int = 8

    #: Ask for an email address too (create_user then gets `email=`).
    ask_email: bool = False

    #: With ask_email: refuse a sign-up without one. False makes it optional.
    require_email: bool = True

    #: With a `verification`: sign the new user in straight away (True), or
    #: only show "check your email" until they confirm (False).
    sign_in_before_verified: bool = True

    def __init__(
        self,
        *,
        templates: Jinja2Templates,
        identity_provider: DevelopmentIdentityProvider,
        verification: "EmailVerificationViews | None" = None,
    ):
        self._templates = templates
        self._identity_provider = identity_provider
        self._verification = verification

    async def is_open(self, request: Request) -> bool:
        """Whether this request may sign up. Default: `signup_open`, and core's
        self_signup_setting when register_settings registered it."""
        # Imported here for the same reason as landing_url below.
        from greentechhub_fastapi.settings import self_signup_open

        return self.signup_open and await self_signup_open(request)

    @abstractmethod
    async def create_user(self, user_id: str, password: str) -> Identity:
        """Store a new user and return their Identity. `user_id` is already
        stripped and the password already checked for length and
        confirmation; hashing it (core's hash_password) is yours. With
        `ask_email` it's called with an `email` keyword too (the checked
        address, or None when optional and left empty), so add one.

        Raise RegistrationError for an expected refusal (the ID is taken, it
        isn't an allowed shape). Let a genuine failure (the database being
        down) propagate; this class doesn't catch it.
        """
        ...

    def router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route(self.register_url, self._register_form, methods=["GET"])
        router.add_api_route(self.register_url, self._register_submit, methods=["POST"])
        return router

    def _context(self, **extra) -> dict:
        context = {
            "register_url": self.register_url,
            "login_url": self.login_url,
            "min_password_length": self.min_password_length,
        }
        if self.ask_email:
            context["ask_email"] = True
        return context | extra

    async def _require_open(self, request: Request) -> None:
        if not await self.is_open(request):
            raise HTTPException(status_code=404)

    def _validate(
        self, user_id: str, password: str, password_confirm: str, email: str = ""
    ) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        if not user_id:
            errors["user_id"] = ["Choose a user ID."]
        if self.ask_email:
            if not email:
                if self.require_email:
                    errors["email"] = ["Enter your email address."]
            elif not email_looks_valid(email):
                errors["email"] = [EMAIL_INVALID]
        problem = password_problem(password, password_confirm, min_length=self.min_password_length)
        if problem:
            field, message = problem
            errors["password" if field == "new" else "password_confirm"] = [message]
        return errors

    def _render(self, request: Request, status_code: int = 200, **extra):
        return self._render_form(request, self.register_template, self._context(**extra),
                                 status_code=status_code)

    async def _register_form(self, request: Request):
        await self._require_open(request)
        return self._render(request)

    async def _register_submit(
        self,
        request: Request,
        user_id: str = Form(""),
        password: str = Form(""),
        password_confirm: str = Form(""),
        email: str = Form(""),
        csrf_token: str = Form(""),
    ):
        await self._require_open(request)
        user_id = user_id.strip()
        email = email.strip() if self.ask_email else ""
        kept = {"user_id": user_id, **({"email": email} if self.ask_email else {})}
        if self._csrf_refused(request, csrf_token):
            return self._render(request, 403, errors={"__all__": [CSRF_REFUSED]}, **kept)
        errors = self._validate(user_id, password, password_confirm, email)
        identity = None
        if not errors:
            try:
                if self.ask_email:
                    identity = await self.create_user(user_id, password, email=email or None)
                else:
                    identity = await self.create_user(user_id, password)
            except RegistrationError as exc:
                errors = exc.errors
        if identity is None:
            return self._render(request, 422, errors=errors, **kept)

        verification = self._verification
        if verification is not None and email:
            try:
                await verification.send_link(request, identity.subject, email)
            except EMAIL_SEND_ERRORS as exc:
                logger.warning("confirmation email for %s not sent: %s", identity.subject, exc)
            if not self.sign_in_before_verified:
                return self._render(request, verify_sent=True, email=email,
                                    verify_resend_url=verification.resend_url)

        # Imported here for the same reason as in LoginViews: settings imports
        # auth.dependency, whose package __init__ imports this module.
        from greentechhub_fastapi.settings import landing_url

        token = self._identity_provider.issue(identity)
        url = await landing_url(request, identity, fallback=self.redirect_url)
        response = RedirectResponse(url=url, status_code=303)
        create_session_cookie(response, token)
        return response
