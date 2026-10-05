"""PasswordResetViews: a forgot form that emails a single-use link without
telling who has an account, the link's new-password form, and the optional
throttle; plus LoginViews' forgot_password_url link."""

import asyncio
import logging
import re

import httpx
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import EmailDeliveryError, InMemoryEmailSender
from greentechhub_core.identity import DevelopmentIdentityProvider
from greentechhub_core.security import (
    InMemoryAttemptStore,
    InMemoryTokenStore,
    LoginThrottle,
    OneTimeTokens,
)
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_email
from greentechhub_fastapi.auth import LoginViews, PasswordResetViews

FORGOT = ("FORGOT at {{ forgot_url }} (login {{ login_url }})"
          "{% if sent %} SENT {{ identifier }}{% endif %}"
          "{% for f, m in (errors or {}).items() %} [{{ f }}: {{ m|join(' ') }}]{% endfor %}")
RESET = ("RESET at {{ action }} (login {{ login_url }}, min {{ min_password_length }})"
         "{% if invalid %} INVALID retry {{ forgot_url }}{% endif %}{% if done %} DONE{% endif %}"
         "{% for f, m in (errors or {}).items() %} [{{ f }}: {{ m|join(' ') }}]{% endfor %}")
LINK = re.compile(r"https://app\.example/reset-password/(\S+)")


def _templates():
    return Jinja2Templates(env=Environment(loader=DictLoader({
        "forgot_password_page.html": FORGOT,
        "reset_password_page.html": RESET,
        "login_page.html": "Log in{% if forgot_password_url %} (forgot: {{ forgot_password_url }})"
                           "{% endif %}",
    })))


class _Reset(PasswordResetViews):
    accounts = {"alice": "alice@example.com"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.passwords: dict[str, list[str]] = {}

    async def find_account(self, identifier):
        for subject, email in self.accounts.items():
            if identifier in (subject, email):
                return subject, email
        return None

    async def set_password(self, subject, password):
        self.passwords.setdefault(subject, []).append(password)


class _Failing(InMemoryEmailSender):
    async def send(self, message):
        raise EmailDeliveryError("couldn't send email through smtp.example.com:587")


def _app(*, sender=None, email=True, throttle=None):
    app = FastAPI()
    sender = sender if sender is not None else InMemoryEmailSender()
    if email:
        register_email(app, None, sender=sender, base_url="https://app.example")
    views = _Reset(templates=_templates(), tokens=OneTimeTokens(InMemoryTokenStore()),
                   throttle=throttle)
    app.include_router(views.router())
    return app, views, sender


def _call(app, method, path, data=None):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            if method == "GET":
                return await client.get(path)
            return await client.post(path, data=data or {})

    return asyncio.run(go())


def _request_link(app, sender, identifier="alice"):
    _call(app, "POST", "/forgot-password", {"identifier": identifier})
    return LINK.search(sender.outbox[-1].text).group(1)


NEW = {"password": "new-secret-1", "password_confirm": "new-secret-1"}


# ── forgot password ────────────────────────────────────────────────────────


def test_the_forgot_form_renders():
    app, _, _ = _app()
    assert _call(app, "GET", "/forgot-password").text == "FORGOT at /forgot-password (login /login)"


def test_a_known_account_is_emailed_a_link_and_an_unknown_one_looks_the_same():
    app, _, sender = _app()
    known = _call(app, "POST", "/forgot-password", {"identifier": "alice@example.com"})
    (message,) = sender.outbox
    assert message.to == ("alice@example.com",) and message.subject == "Reset your password"
    assert LINK.search(message.text) and "within 60 minutes" in message.text
    unknown = _call(app, "POST", "/forgot-password", {"identifier": "mallory"})
    assert len(sender.outbox) == 1
    assert known.status_code == unknown.status_code == 200
    assert known.text.replace("alice@example.com", "X") == unknown.text.replace("mallory", "X")


def test_an_empty_identifier_is_a_field_error():
    app, _, sender = _app()
    response = _call(app, "POST", "/forgot-password", {"identifier": "  "})
    assert response.status_code == 422
    assert "[identifier: Enter your user ID or email.]" in response.text
    assert sender.outbox == []


def test_mail_problems_are_logged_never_shown(caplog):
    for app, _, _ in (_app(sender=_Failing()), _app(email=False)):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="greentechhub_fastapi.auth.reset"):
            response = _call(app, "POST", "/forgot-password", {"identifier": "alice"})
        assert response.status_code == 200 and "SENT alice" in response.text
        assert "password reset email for alice not sent" in caplog.text


# ── choose a new password ──────────────────────────────────────────────────


def test_the_link_shows_the_form_and_a_bad_one_the_invalid_page():
    app, _, sender = _app()
    token = _request_link(app, sender)
    page = _call(app, "GET", f"/reset-password/{token}")
    assert page.status_code == 200
    assert page.text == f"RESET at /reset-password/{token} (login /login, min 8)"
    bad = _call(app, "GET", "/reset-password/not-a-token")
    assert bad.status_code == 400 and "INVALID retry /forgot-password" in bad.text


def test_a_refused_password_leaves_the_link_usable():
    app, views, sender = _app()
    token = _request_link(app, sender)
    short = _call(app, "POST", f"/reset-password/{token}",
                  {"password": "short", "password_confirm": "short"})
    assert short.status_code == 422 and "[password: Use at least 8 characters.]" in short.text
    mismatch = _call(app, "POST", f"/reset-password/{token}",
                     {"password": "new-secret-1", "password_confirm": "new-secret-2"})
    assert mismatch.status_code == 422 and "password_confirm" in mismatch.text
    assert views.passwords == {}
    assert _call(app, "GET", f"/reset-password/{token}").status_code == 200


def test_a_new_password_is_stored_once_and_the_link_is_used_up():
    app, views, sender = _app()
    token = _request_link(app, sender)
    done = _call(app, "POST", f"/reset-password/{token}", NEW)
    assert done.status_code == 200 and done.text.endswith("DONE")
    assert views.passwords == {"alice": ["new-secret-1"]}
    again = _call(app, "POST", f"/reset-password/{token}", NEW)
    assert again.status_code == 400 and "INVALID" in again.text
    assert views.passwords == {"alice": ["new-secret-1"]}


def test_only_the_latest_link_works():
    app, _, sender = _app()
    first = _request_link(app, sender)
    second = _request_link(app, sender)
    assert _call(app, "GET", f"/reset-password/{first}").status_code == 400
    assert _call(app, "GET", f"/reset-password/{second}").status_code == 200


def test_the_throttle_caps_reset_emails():
    throttle = LoginThrottle(InMemoryAttemptStore(), max_failures=2)
    app, _, sender = _app(throttle=throttle)
    statuses = [_call(app, "POST", "/forgot-password", {"identifier": "alice"})
                for _ in range(3)]
    assert [r.status_code for r in statuses] == [200, 200, 429]
    assert statuses[2].headers["retry-after"] == "900"
    assert "Too many reset requests. Try again in 15 minutes." in statuses[2].text
    assert len(sender.outbox) == 2


# ── LoginViews' link ───────────────────────────────────────────────────────


class _Login(LoginViews):
    async def authenticate(self, user_id, password):
        return None


def test_the_login_page_links_to_the_forgot_form_only_when_told():
    provider = DevelopmentIdentityProvider(secret_key="secret")
    plain = FastAPI()
    plain.include_router(_Login(templates=_templates(), identity_provider=provider).router())
    assert _call(plain, "GET", "/login").text == "Log in"
    linked = _Login(templates=_templates(), identity_provider=provider)
    linked.forgot_password_url = "/forgot-password"
    app = FastAPI()
    app.include_router(linked.router())
    assert _call(app, "GET", "/login").text == "Log in (forgot: /forgot-password)"
