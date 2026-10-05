"""RegisterViews' opt-in email: ask_email adds a checked address (passed to
create_user as email=), and a verification emails the confirmation link,
optionally holding the sign-in back until it's confirmed."""

import asyncio
import logging
import re

import httpx
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import EmailDeliveryError, InMemoryEmailSender
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.security import InMemoryTokenStore, OneTimeTokens
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_email
from greentechhub_fastapi.auth import EmailVerificationViews, RegisterViews
from greentechhub_fastapi.auth.cookies import SESSION_COOKIE_NAME

PAGE = ("SIGNUP ask={{ ask_email|default('no') }} email={{ email|default('') }}"
        "{% if verify_sent %} SENT to {{ email }} resend {{ verify_resend_url }}{% endif %}"
        "{% for f, m in (errors or {}).items() %} [{{ f }}: {{ m|join(' ') }}]{% endfor %}")
FORM = {"user_id": "newbie", "password": "long-enough", "password_confirm": "long-enough"}


def _templates():
    return Jinja2Templates(env=Environment(loader=DictLoader({
        "register_page.html": PAGE,
        "verify_email_page.html": "",
        "verify_email_resend_page.html": "",
    })))


class _Register(RegisterViews):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.created: list[tuple] = []

    async def create_user(self, user_id, password, email=None):
        self.created.append((user_id, email))
        return Identity(subject=user_id, username=user_id, email=email, groups=[], claims={})


class _TwoArgs(RegisterViews):
    """A subclass written before ask_email: create_user takes no email."""

    async def create_user(self, user_id, password):
        return Identity(subject=user_id, username=user_id, email=None, groups=[], claims={})


class _Verify(EmailVerificationViews):
    async def mark_verified(self, subject):
        pass

    async def find_unverified(self, identifier):
        return None


class _Failing(InMemoryEmailSender):
    async def send(self, message):
        raise EmailDeliveryError("couldn't send email through smtp.example.com:587")


def _app(views_class=_Register, *, verify=False, sender=None, **attrs):
    app = FastAPI()
    sender = sender if sender is not None else InMemoryEmailSender()
    register_email(app, None, sender=sender)
    verification = (_Verify(templates=_templates(), tokens=OneTimeTokens(InMemoryTokenStore()))
                    if verify else None)
    kwargs = {"verification": verification} if verify else {}
    views = views_class(templates=_templates(),
                        identity_provider=DevelopmentIdentityProvider(secret_key="s"), **kwargs)
    for key, value in attrs.items():
        setattr(views, key, value)
    app.include_router(views.router())
    return app, views, sender


def _post(app, data):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/register", data=data, follow_redirects=False)

    return asyncio.run(go())


def test_off_by_default_and_old_subclasses_still_work():
    app, _, _ = _app(_TwoArgs)
    response = _post(app, FORM)
    assert response.status_code == 303
    app, _, _ = _app(_TwoArgs)
    refused = _post(app, {**FORM, "user_id": ""})
    assert "ask=no" in refused.text


def test_ask_email_requires_and_checks_the_address():
    app, views, _ = _app(ask_email=True)
    missing = _post(app, FORM)
    assert missing.status_code == 422
    assert "ask=True" in missing.text and "[email: Enter your email address.]" in missing.text
    bad = _post(app, {**FORM, "email": "not-an-address"})
    assert bad.status_code == 422 and "like name@example.com" in bad.text
    assert "email=not-an-address" in bad.text  # kept for fixing
    assert views.created == []


def test_create_user_gets_the_email():
    app, views, _ = _app(ask_email=True)
    assert _post(app, {**FORM, "email": " new@example.com "}).status_code == 303
    assert views.created == [("newbie", "new@example.com")]


def test_an_optional_email_may_be_left_empty():
    app, views, _ = _app(ask_email=True, require_email=False)
    assert _post(app, FORM).status_code == 303
    assert views.created == [("newbie", None)]


def test_a_verification_emails_the_link_and_signs_in_by_default():
    app, _, sender = _app(ask_email=True, verify=True)
    response = _post(app, {**FORM, "email": "new@example.com"})
    assert response.status_code == 303 and SESSION_COOKIE_NAME in response.cookies
    (message,) = sender.outbox
    assert message.to == ("new@example.com",)
    assert re.search(r"/verify-email/\S+", message.text)


def test_held_back_until_confirmed():
    app, _, sender = _app(ask_email=True, verify=True, sign_in_before_verified=False)
    response = _post(app, {**FORM, "email": "new@example.com"})
    assert response.status_code == 200 and SESSION_COOKIE_NAME not in response.cookies
    assert "SENT to new@example.com resend /verify-email/resend" in response.text
    assert len(sender.outbox) == 1


def test_a_mail_failure_is_logged_and_the_account_stands(caplog):
    app, views, _ = _app(ask_email=True, verify=True, sender=_Failing(),
                         sign_in_before_verified=False)
    with caplog.at_level(logging.WARNING, logger="greentechhub_fastapi.auth.register"):
        response = _post(app, {**FORM, "email": "new@example.com"})
    assert response.status_code == 200 and "SENT to new@example.com" in response.text
    assert views.created == [("newbie", "new@example.com")]
    assert "confirmation email for newbie not sent" in caplog.text


def test_without_a_verification_nothing_is_emailed():
    app, _, sender = _app(ask_email=True)
    assert _post(app, {**FORM, "email": "new@example.com"}).status_code == 303
    assert sender.outbox == []
