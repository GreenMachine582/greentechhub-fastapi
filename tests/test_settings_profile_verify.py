"""SettingsViews' profile with `verification`: a changed, non-empty email is
sent a confirmation link after the save, with the toast saying so; mail
problems are logged and the profile is still saved."""

import json
import logging

from fastapi.templating import Jinja2Templates
from greentechhub_core.email import EmailDeliveryError, InMemoryEmailSender
from greentechhub_core.security import InMemoryTokenStore, OneTimeTokens
from greentechhub_core.settings import InMemorySettingsStore
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_email, register_permissions, register_settings
from greentechhub_fastapi.auth import EmailVerificationViews
from greentechhub_fastapi.settings import SettingsViews
from tests.conftest import build_app
from tests.test_settings import (  # noqa: F401
    ROLES,
    _post,
    _registry,
    _run,
    role_settings,
    templates,
)
from tests.test_settings_profile import _Profiles


class _Verify(EmailVerificationViews):
    async def mark_verified(self, subject):
        pass

    async def find_unverified(self, identifier):
        return None


class _Failing(InMemoryEmailSender):
    async def send(self, message):
        raise EmailDeliveryError("couldn't send email through smtp.example.com:587")


def _app(role_settings, templates, *, sender=None, verify=True):  # noqa: F811
    app = build_app(role_settings)
    register_permissions(app, role_settings, roles=ROLES)
    sender = sender if sender is not None else InMemoryEmailSender()
    register_email(app, role_settings, sender=sender)
    profiles = _Profiles()  # alice starts as alice@old.example
    verification = None
    if verify:
        blank = Jinja2Templates(env=Environment(loader=DictLoader({})))
        verification = _Verify(templates=blank, tokens=OneTimeTokens(InMemoryTokenStore()))
    views = SettingsViews(templates=templates, load_profile=profiles.load,
                          save_profile=profiles.save, verification=verification)
    register_settings(app, role_settings, registry=_registry(), store=InMemorySettingsStore(),
                      views=views)
    return app, profiles, sender


def _save(app, display_name="Alice", email="alice@old.example"):
    response = _run(app, _post("/settings/profile",
                               {"display_name": display_name, "email": email}),
                    subject="alice")
    toast = json.loads(response.headers["HX-Trigger"])["showToast"]["message"] \
        if response.status_code == 200 else None
    return response, toast


def test_a_changed_email_is_sent_its_confirmation_link(role_settings, templates):  # noqa: F811
    app, profiles, sender = _app(role_settings, templates)
    response, toast = _save(app, email="alice@new.example")
    assert response.status_code == 200
    assert toast == "Profile saved. We've emailed a link to confirm alice@new.example."
    (message,) = sender.outbox
    assert message.to == ("alice@new.example",) and "/verify-email/" in message.text
    assert profiles.store["alice"].email == "alice@new.example"


def test_an_unchanged_or_cleared_email_sends_nothing(role_settings, templates):  # noqa: F811
    app, _, sender = _app(role_settings, templates)
    assert _save(app, email="Alice@OLD.example")[1] == "Profile saved"
    assert _save(app, display_name="Al")[1] == "Profile saved"
    assert _save(app, email="")[1] == "Profile saved"
    assert sender.outbox == []


def test_without_a_verification_nothing_is_sent(role_settings, templates):  # noqa: F811
    app, _, sender = _app(role_settings, templates, verify=False)
    assert _save(app, email="alice@new.example")[1] == "Profile saved"
    assert sender.outbox == []


def test_a_mail_failure_is_logged_and_the_profile_kept(role_settings, templates,  # noqa: F811
                                                        caplog):
    app, profiles, _ = _app(role_settings, templates, sender=_Failing())
    with caplog.at_level(logging.WARNING, logger="greentechhub_fastapi.settings"):
        response, toast = _save(app, email="alice@new.example")
    assert response.status_code == 200
    assert toast == "Profile saved, but the confirmation email couldn't be sent."
    assert profiles.store["alice"].email == "alice@new.example"
    assert "confirmation email for alice not sent" in caplog.text


def test_a_refused_save_sends_nothing(role_settings, templates):  # noqa: F811
    app, _, sender = _app(role_settings, templates)
    assert _save(app, email="not-an-address")[0].status_code == 422
    assert _save(app, email="taken@example.com")[0].status_code == 422  # ProfileError
    assert sender.outbox == []
