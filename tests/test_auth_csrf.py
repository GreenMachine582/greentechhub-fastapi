"""Opt-in CSRF on the auth views (csrf = True): a double-submit cookie, the
same token in the rendered form, and every POST checked first — 403 on a
mismatch, before anything else runs. The client talks https so the secure
cookie round-trips."""

import asyncio
import re

import httpx
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import InMemoryEmailSender
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.security import (
    InMemoryAttemptStore,
    InMemoryTokenStore,
    LoginThrottle,
    OneTimeTokens,
)
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_email
from greentechhub_fastapi.auth import (
    EmailVerificationViews,
    LoginViews,
    PasswordResetViews,
    RegisterViews,
)
from greentechhub_fastapi.auth.cookies import SESSION_COOKIE_NAME
from greentechhub_fastapi.auth.csrf import CSRF_COOKIE_NAME, csrf_ok

PAGE = ("TOKEN={{ csrf_token|default('none') }}{% if error %} ERROR={{ error }}{% endif %}"
        "{% for f, m in (errors or {}).items() %} ERR {{ f }}={{ m|join(';') }}{% endfor %}")
TOKEN = re.compile(r"TOKEN=(\S+)")
ALICE = Identity(subject="alice", username="alice", email=None, groups=[], claims={})


def _templates():
    names = ["login_page.html", "register_page.html", "forgot_password_page.html",
             "reset_password_page.html", "verify_email_page.html", "verify_email_resend_page.html"]
    return Jinja2Templates(env=Environment(loader=DictLoader({n: PAGE for n in names})))


class _Login(LoginViews):
    csrf = True
    calls = 0

    async def authenticate(self, user_id, password):
        type(self).calls += 1
        return ALICE if password == "s3cret" else None


class _Register(RegisterViews):
    csrf = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.created: list[str] = []

    async def create_user(self, user_id, password):
        self.created.append(user_id)
        return Identity(subject=user_id, username=user_id, email=None, groups=[], claims={})


class _Reset(PasswordResetViews):
    csrf = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.passwords: dict[str, str] = {}

    async def find_account(self, identifier):
        return ("alice", "alice@example.com") if identifier == "alice" else None

    async def set_password(self, subject, password):
        self.passwords[subject] = password


class _Verify(EmailVerificationViews):
    csrf = True

    async def mark_verified(self, subject):
        pass

    async def find_unverified(self, identifier):
        return ("alice", "alice@example.com") if identifier == "alice" else None


def _app(throttle=None):
    app = FastAPI()
    provider = DevelopmentIdentityProvider(secret_key="secret")
    tokens = OneTimeTokens(InMemoryTokenStore())
    sender = InMemoryEmailSender()
    register_email(app, None, sender=sender)
    login = _Login(templates=_templates(), identity_provider=provider, throttle=throttle)
    register = _Register(templates=_templates(), identity_provider=provider)
    reset = _Reset(templates=_templates(), tokens=tokens)
    verify = _Verify(templates=_templates(), tokens=tokens)
    for views in (login, register, reset, verify):
        app.include_router(views.router())
    _Login.calls = 0
    return app, register, reset, tokens, sender


def _session(app, steps):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            return [await step(client) for step in steps]

    return asyncio.run(go())


def _get(path):
    return lambda client: client.get(path)


def _post(path, data, token=None):
    async def step(client):
        form = dict(data)
        if token == "page":
            page = await client.get(path)
            form["csrf_token"] = TOKEN.search(page.text).group(1)
        elif token is not None:
            form["csrf_token"] = token
        return await client.post(path, data=form, follow_redirects=False)

    return step


LOGIN = {"user_id": "alice", "password": "s3cret"}


def test_the_form_page_sets_the_cookie_and_renders_the_same_token():
    app, *_ = _app()
    first, second = _session(app, [_get("/login"), _get("/login")])
    token = TOKEN.search(first.text).group(1)
    assert token != "none" and first.cookies[CSRF_COOKIE_NAME] == token
    assert TOKEN.search(second.text).group(1) == token  # reused, not rotated


def test_login_without_or_with_a_wrong_token_is_refused_before_authenticating():
    app, *_ = _app()
    missing, wrong = _session(app, [_post("/login", LOGIN), _post("/login", LOGIN, "forged")])
    for response in (missing, wrong):
        assert response.status_code == 403
        assert "ERROR=Your session expired. Please try again." in response.text
        assert SESSION_COOKIE_NAME not in response.cookies
    assert _Login.calls == 0


def test_login_with_the_pages_token_signs_in():
    app, *_ = _app()
    (response,) = _session(app, [_post("/login", LOGIN, "page")])
    assert response.status_code == 303 and SESSION_COOKIE_NAME in response.cookies


def test_a_csrf_failure_is_not_a_login_failure():
    throttle = LoginThrottle(InMemoryAttemptStore(), max_failures=1)
    app, *_ = _app(throttle)
    responses = _session(app, [_post("/login", LOGIN), _post("/login", LOGIN, "page")])
    assert [r.status_code for r in responses] == [403, 303]


def test_register_checks_the_token_before_creating():
    app, register, *_ = _app()
    form = {"user_id": "newbie", "password": "long-enough", "password_confirm": "long-enough"}
    refused, created = _session(app, [_post("/register", form),
                                      _post("/register", form, "page")])
    assert refused.status_code == 403 and "ERR __all__=Your session expired" in refused.text
    assert created.status_code == 303 and register.created == ["newbie"]


def test_forgot_password_sends_nothing_without_the_token():
    app, _, _, _, sender = _app()
    refused, sent = _session(app, [_post("/forgot-password", {"identifier": "alice"}),
                                   _post("/forgot-password", {"identifier": "alice"}, "page")])
    assert refused.status_code == 403 and "ERR identifier=Your session expired" in refused.text
    assert sent.status_code == 200 and len(sender.outbox) == 1


def test_a_refused_reset_leaves_the_link_usable():
    app, _, reset, tokens, _ = _app()
    link = asyncio.run(tokens.issue("alice", reset.PURPOSE))
    form = {"password": "brand-new-1", "password_confirm": "brand-new-1"}
    refused, done = _session(app, [_post(f"/reset-password/{link}", form),
                                   _post(f"/reset-password/{link}", form, "page")])
    assert refused.status_code == 403 and "ERR __all__=Your session expired" in refused.text
    # The refusal didn't use the link up: the next, valid post still works.
    assert done.status_code == 200 and reset.passwords == {"alice": "brand-new-1"}


def test_resend_is_checked_but_the_emailed_link_is_a_plain_get():
    app, _, _, tokens, sender = _app()
    link = asyncio.run(tokens.issue("alice", "email_verification"))
    refused, opened = _session(app, [_post("/verify-email/resend", {"identifier": "alice"}),
                                     _get(f"/verify-email/{link}")])
    assert refused.status_code == 403 and sender.outbox == []
    assert opened.status_code == 200


def test_an_empty_cookie_or_field_never_passes():
    class _Request:
        def __init__(self, cookie):
            self.cookies = {CSRF_COOKIE_NAME: cookie} if cookie is not None else {}

    assert not csrf_ok(_Request(None), "x")
    assert not csrf_ok(_Request(""), "")
    assert not csrf_ok(_Request("abc"), "")
    assert csrf_ok(_Request("abc"), "abc")


def test_off_by_default():
    class Plain(LoginViews):
        async def authenticate(self, user_id, password):
            return ALICE

    app = FastAPI()
    app.include_router(Plain(templates=_templates(),
                             identity_provider=DevelopmentIdentityProvider(secret_key="s")).router())
    page, login = _session(app, [_get("/login"), _post("/login", LOGIN)])
    assert "TOKEN=none" in page.text and CSRF_COOKIE_NAME not in page.cookies
    assert login.status_code == 303
