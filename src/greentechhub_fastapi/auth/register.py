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
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi.auth.cookies import create_session_cookie


class RegistrationError(Exception):
    """Raised by `RegisterViews.create_user` for an expected refusal, e.g. a
    user ID that's taken. `errors` maps form fields ("user_id", "password")
    to their messages; the form is shown again with them, status 422."""

    def __init__(self, errors: Mapping[str, list[str]]) -> None:
        super().__init__("; ".join(m for messages in errors.values() for m in messages))
        self.errors = {field: list(messages) for field, messages in errors.items()}


class RegisterViews(ABC):
    """Subclass and implement `create_user()`, then mount `.router()`.

    Ships GET/POST `register_url`. A successful sign-up signs the new user in
    and lands them where a login would (the user's landing page when
    register_settings registered core's landing_page_setting, else
    `redirect_url`). While `is_open(request)` is False both routes answer
    404, so a closed sign-up looks like no sign-up at all.

    The template gets {"register_url", "login_url", "min_password_length"},
    plus {"errors", "user_id"} after a refused sign-up — errors as
    {field: [message]}; the user ID is kept, a password never is.
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

    def __init__(
        self, *, templates: Jinja2Templates, identity_provider: DevelopmentIdentityProvider
    ):
        self._templates = templates
        self._identity_provider = identity_provider

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
        confirmation; hashing it (core's hash_password) is yours.

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
        return {
            "register_url": self.register_url,
            "login_url": self.login_url,
            "min_password_length": self.min_password_length,
            **extra,
        }

    async def _require_open(self, request: Request) -> None:
        if not await self.is_open(request):
            raise HTTPException(status_code=404)

    def _validate(self, user_id: str, password: str, password_confirm: str) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        if not user_id:
            errors["user_id"] = ["Choose a user ID."]
        if len(password) < self.min_password_length:
            errors["password"] = [f"Use at least {self.min_password_length} characters."]
        elif password != password_confirm:
            errors["password_confirm"] = ["The passwords don't match."]
        return errors

    async def _register_form(self, request: Request):
        await self._require_open(request)
        return self._templates.TemplateResponse(request, self.register_template, self._context())

    async def _register_submit(
        self,
        request: Request,
        user_id: str = Form(""),
        password: str = Form(""),
        password_confirm: str = Form(""),
    ):
        await self._require_open(request)
        user_id = user_id.strip()
        errors = self._validate(user_id, password, password_confirm)
        identity = None
        if not errors:
            try:
                identity = await self.create_user(user_id, password)
            except RegistrationError as exc:
                errors = exc.errors
        if identity is None:
            return self._templates.TemplateResponse(
                request,
                self.register_template,
                self._context(errors=errors, user_id=user_id),
                status_code=422,
            )

        # Imported here for the same reason as in LoginViews: settings imports
        # auth.dependency, whose package __init__ imports this module.
        from greentechhub_fastapi.settings import landing_url

        token = self._identity_provider.issue(identity)
        url = await landing_url(request, identity, fallback=self.redirect_url)
        response = RedirectResponse(url=url, status_code=303)
        create_session_cookie(response, token)
        return response
