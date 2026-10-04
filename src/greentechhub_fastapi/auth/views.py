"""views — optional login/logout route scaffolding for the "local" auth
adapter.

docs/auth.md has always said login/logout routes are "thin" and left them to
each service to hand-write, since a service's own credential-check logic
(its own User model, its own password hashing) can't live here. That much is
still true — but the *rest* of a local-auth login route (render a form,
verify credentials, build an Identity, issue a session JWT via
DevelopmentIdentityProvider, set/clear the cookie, redirect) is identical
across every service that picks AUTH_ADAPTER=local, and was on track to be
copy-pasted into each one (confirmed: PyFinBot's first web UI pass wrote
this exact sequence by hand). LoginViews exists so that only the
credential-check step is service-specific.

A class, not another build_*_get_current_user()-style factory (the pattern
the rest of this auth/ package uses): the thing being reused here is a
small *cluster* of related behavior (three routes sharing config — template
name, redirect targets, the identity provider) with one deliberate override
point, not a single callable closing over config. Subclassing expresses
"same flow, different credential check" more directly than a factory taking
a credential-check callback would.

Deliberately does not know about sessions, ORMs, or any particular
database — authenticate() is a plain async method; a subclass acquires
whatever resources it needs (a DB session, an HTTP call to another service,
anything) entirely on its own. Keeping this class framework/ORM-agnostic
matches every other module in this package (see e.g. identity.provider's own
"never sees a Request/Response" posture in greentechhub-core).

Also deliberately does not construct its own DevelopmentIdentityProvider
from a bare secret_key — the caller passes an already-configured one in.
register_auth(app, settings) is the precedent: it reads AUTH_ADAPTER and
picks/builds the right provider itself, rather than a shared class assuming
"local" and hardcoding DevelopmentIdentityProvider deep inside. LoginViews
follows the same rule — config-driven provider choice stays with the
caller (who already knows its own AUTH_ADAPTER/settings), never hardcoded
here. In practice this is still always a DevelopmentIdentityProvider today
(LoginViews is inherently a local-style password-form flow — forward_auth
has no equivalent, since Authentik issues its own session externally and
there's no form to submit), but the caller decides that, not this class.
"""

from abc import ABC, abstractmethod

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

from greentechhub_fastapi.auth.cookies import clear_session_cookie, create_session_cookie


class LoginViews(ABC):
    """Subclass and implement `authenticate()`, then mount `.router()`.

    Ships GET/POST /login and POST /logout. Not prefixed — mount at whatever
    path the service wants these to live at (matching how register_auth
    itself takes no path opinion either).

    A successful login lands on the user's chosen page when register_settings
    registered core's landing_page_setting (settings.landing_url), else on
    `redirect_url`.
    """

    #: Template name resolved against the Jinja2Templates instance passed to
    #: __init__. Defaults to greentechhub-ui's ready-made sign-in page (ui
    #: v0.14+; this package still doesn't import ui), which renders exactly
    #: this context: {"login_url"} on GET, plus {"error", "user_id"} after a
    #: failed login (the user ID is kept so it needn't be retyped; the
    #: password never is). Set your own template name to keep a custom page.
    login_template: str = "login_page.html"

    #: Where a successful login redirects to — or, when the service registered
    #: core's landing_page_setting, the fallback if it can't be resolved.
    redirect_url: str = "/"

    #: Where GET /login lives — logout redirects here, and this is also
    #: this class's own mount path for the two /login routes.
    login_url: str = "/login"

    #: The sign-up page (RegisterViews.register_url) when the service offers
    #: one; passed to the template as `register_url` so it can show a "Create
    #: account" link. None (the default) leaves it out.
    register_url: str | None = None

    def __init__(
        self, *, templates: Jinja2Templates, identity_provider: DevelopmentIdentityProvider
    ):
        self._templates = templates
        self._identity_provider = identity_provider

    @abstractmethod
    async def authenticate(self, user_id: str, password: str) -> Identity | None:
        """Return a resolved Identity for valid credentials, None otherwise.

        Never raises for "wrong password"/"no such user" — those are
        ordinary, expected outcomes under this Identity | None contract
        (same treatment IdentityProvider.resolve gives an invalid token),
        not error conditions. Let a genuine failure (e.g. the database being
        down) propagate as an exception; this class doesn't catch it.
        """
        ...

    def router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route(self.login_url, self._login_form, methods=["GET"])
        router.add_api_route(self.login_url, self._login_submit, methods=["POST"])
        router.add_api_route("/logout", self._logout, methods=["POST"])
        return router

    def _context(self, **extra) -> dict:
        context = {"login_url": self.login_url, **extra}
        if self.register_url:
            context["register_url"] = self.register_url
        return context

    async def _login_form(self, request: Request):
        return self._templates.TemplateResponse(request, self.login_template, self._context())

    async def _login_submit(
        self, request: Request, user_id: str = Form(...), password: str = Form(...)
    ):
        identity = await self.authenticate(user_id, password)
        if identity is None:
            return self._templates.TemplateResponse(
                request,
                self.login_template,
                self._context(error="Incorrect user ID or password", user_id=user_id),
                status_code=401,
            )

        # Imported here: greentechhub_fastapi.settings imports auth.dependency,
        # whose package __init__ imports this module.
        from greentechhub_fastapi.settings import landing_url

        token = self._identity_provider.issue(identity)
        url = await landing_url(request, identity, fallback=self.redirect_url)
        response = RedirectResponse(url=url, status_code=303)
        create_session_cookie(response, token)
        return response

    async def _logout(self):
        response = RedirectResponse(url=self.login_url, status_code=303)
        clear_session_cookie(response)
        return response
