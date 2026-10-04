"""RegisterViews: self-service sign-up with only create_user() left to the
service, plus LoginViews' optional register_url link."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.identity.models import RawAuthContext
from greentechhub_core.settings import InMemorySettingsStore, SettingsRegistry
from greentechhub_core.settings.builtins import landing_page_setting
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_settings
from greentechhub_fastapi.auth import LoginViews, RegisterViews, RegistrationError
from greentechhub_fastapi.auth.cookies import SESSION_COOKIE_NAME
from tests.conftest import build_app
from tests.test_settings import role_settings  # noqa: F401

SECRET = "register-secret"
PAGE = (
    "Sign up at {{ register_url }} (sign in: {{ login_url }}, min {{ min_password_length }})"
    "{% for field, messages in (errors or {}).items() %}"
    " [{{ field }}: {{ messages|join(' ') }}]{% endfor %}"
    "{% if user_id %} as {{ user_id }}{% endif %}"
)


def _templates() -> Jinja2Templates:
    return Jinja2Templates(env=Environment(loader=DictLoader({
        "register_page.html": PAGE,
        "signup.html": "Custom sign-up",
        "login_page.html": "Log in{% if register_url %} or create an account at"
                           " {{ register_url }}{% endif %}",
    })))


class _Register(RegisterViews):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.users: dict[str, str] = {"taken": "pw"}

    async def create_user(self, user_id, password):
        if user_id in self.users:
            raise RegistrationError({"user_id": ["That user ID is taken."]})
        self.users[user_id] = password
        return Identity(subject=user_id, username=user_id, email=None, groups=[], claims={})


class _Login(LoginViews):
    async def authenticate(self, user_id, password):
        return None


def _provider() -> DevelopmentIdentityProvider:
    return DevelopmentIdentityProvider(secret_key=SECRET)


def _views(**attrs) -> _Register:
    views = _Register(templates=_templates(), identity_provider=_provider())
    for key, value in attrs.items():
        setattr(views, key, value)
    return views


def _app(views: RegisterViews, app: FastAPI | None = None) -> FastAPI:
    app = app or FastAPI()
    app.include_router(views.router())
    return app


def _call(app, method, path, data=None):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            if method == "GET":
                return await client.get(path)
            return await client.post(path, data=data or {}, follow_redirects=False)

    return asyncio.run(run())


def _form(user_id="newbie", password="long-enough", confirm=None):
    return {"user_id": user_id, "password": password,
            "password_confirm": password if confirm is None else confirm}


def test_form_renders_with_its_context():
    response = _call(_app(_views()), "GET", "/register")
    assert response.status_code == 200
    assert response.text == "Sign up at /register (sign in: /login, min 8)"


def test_sign_up_creates_the_user_and_signs_them_in():
    views = _views()
    response = _call(_app(views), "POST", "/register", _form(user_id="  newbie "))
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert views.users["newbie"] == "long-enough"
    token = response.cookies[SESSION_COOKIE_NAME]
    identity = _provider().resolve_sync(RawAuthContext(token=token))
    assert identity is not None and identity.subject == "newbie"


@pytest.mark.parametrize(("form", "field", "message"), [
    (_form(user_id="  "), "user_id", "Choose a user ID."),
    (_form(password="short"), "password", "Use at least 8 characters."),
    (_form(confirm="long-enougH"), "password_confirm", "The passwords don't match."),
])
def test_base_validation_rerenders_with_field_errors(form, field, message):
    views = _views()
    response = _call(_app(views), "POST", "/register", form)
    assert response.status_code == 422
    assert f"[{field}: {message}]" in response.text
    assert form["password"] not in response.text
    assert len(views.users) == 1  # nothing created


def test_a_refused_sign_up_keeps_the_user_id_but_never_the_password():
    response = _call(_app(_views()), "POST", "/register", _form(user_id="taken"))
    assert response.status_code == 422
    assert "[user_id: That user ID is taken.]" in response.text
    assert "as taken" in response.text
    assert "long-enough" not in response.text


def test_closed_sign_up_is_a_404():
    app = _app(_views(signup_open=False))
    assert _call(app, "GET", "/register").status_code == 404
    assert _call(app, "POST", "/register", _form()).status_code == 404


def test_is_open_can_decide_per_request():
    class InviteOnly(_Register):
        async def is_open(self, request: Request) -> bool:
            return request.query_params.get("invite") == "yes"

    app = _app(InviteOnly(templates=_templates(), identity_provider=_provider()))
    assert _call(app, "GET", "/register").status_code == 404
    assert _call(app, "GET", "/register?invite=yes").status_code == 200


def test_custom_template_url_and_redirect():
    app = _app(_views(register_template="signup.html", register_url="/join",
                      redirect_url="/welcome"))
    assert _call(app, "GET", "/join").text == "Custom sign-up"
    assert _call(app, "POST", "/join", _form()).headers["location"] == "/welcome"


def test_new_users_land_on_the_landing_page_setting(role_settings):  # noqa: F811
    app = build_app(role_settings)
    landing = landing_page_setting({"/": "Home", "/reports": "Reports"}, default="/reports")
    register_settings(app, role_settings, registry=SettingsRegistry([landing]),
                      store=InMemorySettingsStore())
    response = _call(_app(_views(), app), "POST", "/register", _form())
    assert response.headers["location"] == "/reports"


def test_login_page_links_to_sign_up_only_when_told():
    provider = _provider()
    plain = FastAPI()
    plain.include_router(_Login(templates=_templates(), identity_provider=provider).router())
    assert _call(plain, "GET", "/login").text == "Log in"

    linked = _Login(templates=_templates(), identity_provider=provider)
    linked.register_url = "/register"
    app = FastAPI()
    app.include_router(linked.router())
    assert _call(app, "GET", "/login").text == "Log in or create an account at /register"
    failed = _call(app, "POST", "/login", {"user_id": "x", "password": "y"})
    assert failed.status_code == 401 and "/register" in failed.text
