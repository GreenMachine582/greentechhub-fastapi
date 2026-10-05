"""EmailVerificationViews: send_link, the emailed link that confirms an
address once, the no-enumeration resend form and its throttle; plus
LoginViews.refuse_sign_in, the opt-in gate on unconfirmed accounts."""

import asyncio
import logging
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import EmailDeliveryError, InMemoryEmailSender
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.security import (
    InMemoryAttemptStore,
    InMemoryTokenStore,
    LoginThrottle,
    OneTimeTokens,
)
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_email
from greentechhub_fastapi.auth import EmailVerificationViews, LoginViews
from greentechhub_fastapi.auth.cookies import SESSION_COOKIE_NAME

VERIFY = ("VERIFY (login {{ login_url }}){% if done %} DONE{% endif %}"
          "{% if invalid %} INVALID resend {{ resend_url }}{% endif %}")
RESEND = ("RESEND at {{ resend_url }} (login {{ login_url }})"
          "{% if sent %} SENT {{ identifier }}{% endif %}"
          "{% for f, m in (errors or {}).items() %} [{{ f }}: {{ m|join(' ') }}]{% endfor %}")
LOGIN = ("Log in{% if error %}: {{ error }} as {{ user_id }}{% endif %}"
         "{% if verify_resend_url %} (resend: {{ verify_resend_url }}){% endif %}")
LINK = re.compile(r"https://app\.example/verify-email/(\S+)")


def _templates():
    return Jinja2Templates(env=Environment(loader=DictLoader({
        "verify_email_page.html": VERIFY,
        "verify_email_resend_page.html": RESEND,
        "login_page.html": LOGIN,
    })))


class _Verify(EmailVerificationViews):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.addresses = {"alice": "alice@example.com"}
        self.verified: list[str] = []

    async def mark_verified(self, subject):
        self.verified.append(subject)

    async def find_unverified(self, identifier):
        for subject, address in self.addresses.items():
            if identifier in (subject, address) and subject not in self.verified:
                return subject, address
        return None


class _Failing(InMemoryEmailSender):
    async def send(self, message):
        raise EmailDeliveryError("couldn't send email through smtp.example.com:587")


def _app(*, sender=None, email=True, throttle=None):
    app = FastAPI()
    sender = sender if sender is not None else InMemoryEmailSender()
    if email:
        register_email(app, None, sender=sender, base_url="https://app.example")
    views = _Verify(templates=_templates(), tokens=OneTimeTokens(InMemoryTokenStore()),
                    throttle=throttle)
    app.include_router(views.router())
    return app, views, sender


def _call(app, method, path, data=None):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            if method == "GET":
                return await client.get(path)
            return await client.post(path, data=data or {}, follow_redirects=False)

    return asyncio.run(go())


# ── the link ───────────────────────────────────────────────────────────────


def test_the_emailed_link_confirms_the_address_once():
    app, views, sender = _app()
    asyncio.run(views.send_link(app, "alice", "alice@example.com"))
    (message,) = sender.outbox
    assert message.to == ("alice@example.com",) and message.subject == "Confirm your email address"
    assert "within 48 hours" in message.text
    token = LINK.search(message.text).group(1)
    done = _call(app, "GET", f"/verify-email/{token}")
    assert done.status_code == 200 and done.text == "VERIFY (login /login) DONE"
    assert views.verified == ["alice"]
    again = _call(app, "GET", f"/verify-email/{token}")
    assert again.status_code == 400 and "INVALID resend /verify-email/resend" in again.text
    assert _call(app, "GET", "/verify-email/nope").status_code == 400
    assert views.verified == ["alice"]


def test_send_link_needs_register_email():
    app, views, _ = _app(email=False)
    with pytest.raises(RuntimeError, match="register_email"):
        asyncio.run(views.send_link(app, "alice", "alice@example.com"))


# ── send it again ──────────────────────────────────────────────────────────


def test_resend_looks_the_same_for_an_unknown_account():
    app, _, sender = _app()
    assert _call(app, "GET", "/verify-email/resend").text == (
        "RESEND at /verify-email/resend (login /login)")
    known = _call(app, "POST", "/verify-email/resend", {"identifier": "alice@example.com"})
    assert len(sender.outbox) == 1 and LINK.search(sender.outbox[0].text)
    unknown = _call(app, "POST", "/verify-email/resend", {"identifier": "mallory"})
    assert len(sender.outbox) == 1
    assert known.status_code == unknown.status_code == 200
    assert known.text.replace("alice@example.com", "X") == unknown.text.replace("mallory", "X")


def test_an_empty_identifier_is_a_field_error():
    app, _, _ = _app()
    response = _call(app, "POST", "/verify-email/resend", {"identifier": ""})
    assert response.status_code == 422
    assert "[identifier: Enter your user ID or email.]" in response.text


def test_a_resend_mail_failure_is_logged_not_shown(caplog):
    app, _, _ = _app(sender=_Failing())
    with caplog.at_level(logging.WARNING, logger="greentechhub_fastapi.auth.verify"):
        response = _call(app, "POST", "/verify-email/resend", {"identifier": "alice"})
    assert response.status_code == 200 and "SENT alice" in response.text
    assert "verification email for alice not sent" in caplog.text


def test_the_throttle_caps_resend_emails():
    app, _, sender = _app(throttle=LoginThrottle(InMemoryAttemptStore(), max_failures=2))
    statuses = [_call(app, "POST", "/verify-email/resend", {"identifier": "alice"})
                for _ in range(3)]
    assert [r.status_code for r in statuses] == [200, 200, 429]
    assert statuses[2].headers["retry-after"] == "900"
    assert len(sender.outbox) == 2


# ── LoginViews' gate ───────────────────────────────────────────────────────


ALICE = Identity(subject="alice", username="alice", email=None, groups=[], claims={})


class _Login(LoginViews):
    confirmed = False

    async def authenticate(self, user_id, password):
        return ALICE if (user_id, password) == ("alice", "s3cret") else None

    async def refuse_sign_in(self, identity):
        return None if self.confirmed else "Confirm your email address first."


def _login_app(**attrs):
    views = _Login(templates=_templates(),
                   identity_provider=DevelopmentIdentityProvider(secret_key="secret"))
    for key, value in attrs.items():
        setattr(views, key, value)
    app = FastAPI()
    app.include_router(views.router())
    return app


def test_an_unconfirmed_account_is_turned_away_without_a_session():
    app = _login_app(verify_resend_url="/verify-email/resend")
    response = _call(app, "POST", "/login", {"user_id": "alice", "password": "s3cret"})
    assert response.status_code == 403
    assert response.text == ("Log in: Confirm your email address first. as alice"
                             " (resend: /verify-email/resend)")
    assert SESSION_COOKIE_NAME not in response.cookies


def test_a_confirmed_account_signs_in():
    response = _call(_login_app(confirmed=True), "POST", "/login",
                     {"user_id": "alice", "password": "s3cret"})
    assert response.status_code == 303 and SESSION_COOKIE_NAME in response.cookies


def test_by_default_nobody_is_refused():
    class Plain(LoginViews):
        async def authenticate(self, user_id, password):
            return ALICE

    views = Plain(templates=_templates(),
                  identity_provider=DevelopmentIdentityProvider(secret_key="secret"))
    app = FastAPI()
    app.include_router(views.router())
    response = _call(app, "POST", "/login", {"user_id": "alice", "password": "x"})
    assert response.status_code == 303
