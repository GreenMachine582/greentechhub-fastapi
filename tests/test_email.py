"""register_email, send_email / get_email_sender / recipient_address, and
notify()'s email channel: delivered per the person's preference, with
mail problems logged rather than raised."""

import asyncio
import logging

import httpx
import pytest
from fastapi import Depends, FastAPI
from greentechhub_core.email import EmailDeliveryError, InMemoryEmailSender, new_email
from greentechhub_core.identity import Identity
from greentechhub_core.notifications import InMemoryNotificationStore, notification_preferences
from greentechhub_core.settings import InMemorySettingsStore, SettingsRegistry

from greentechhub_fastapi import register_email, register_notifications, register_settings
from greentechhub_fastapi.email import get_email_sender, recipient_address, send_email
from greentechhub_fastapi.notifications import notify
from greentechhub_fastapi.settings import get_settings_config
from tests.conftest import build_app
from tests.test_settings import role_settings  # noqa: F401

ADDRESSES = {"bob": "bob@example.com"}


async def _address_for(subject):
    return ADDRESSES.get(subject)


def _identity(subject, email=None):
    return Identity(subject=subject, username=subject, email=email, groups=[], claims={})


class _Failing(InMemoryEmailSender):
    async def send(self, message):
        raise EmailDeliveryError("couldn't send email through smtp.example.com:587")


def _app(role_settings, *, sender=None, choice=None, email=True, **email_kwargs):  # noqa: F811
    app = build_app(role_settings)
    if choice is not None:
        registry = SettingsRegistry(list(notification_preferences({"sync": "Sync results"})))
        register_settings(app, role_settings, registry=registry, store=InMemorySettingsStore())
        get_settings_config(app).settings.set_user_sync(_identity("alice"), "notify.sync", choice)
        get_settings_config(app).settings.set_user_sync(_identity("bob"), "notify.sync", choice)
    store = InMemoryNotificationStore()
    register_notifications(app, role_settings, store=store)
    sender = sender or InMemoryEmailSender()
    if email:
        register_email(app, role_settings, sender=sender, address_for=_address_for, **email_kwargs)
    return app, store, sender


PAYLOAD = {"message": "ASX sync finished", "kind": "success",
           "action": {"label": "Open stocks", "url": "/stocks"}}


# ── register_email and helpers ─────────────────────────────────────────────


def test_send_email_goes_through_the_registered_sender(role_settings):  # noqa: F811
    app, _, sender = _app(role_settings)
    asyncio.run(send_email(app, new_email("a@example.com", "Hi", "Hello")))
    assert [m.subject for m in sender.outbox] == ["Hi"]


def test_send_email_needs_register_email():
    with pytest.raises(RuntimeError, match="register_email"):
        asyncio.run(send_email(FastAPI(), new_email("a@example.com", "Hi", "Hello")))


def test_get_email_sender_in_a_route(role_settings):  # noqa: F811
    app, _, sender = _app(role_settings)

    @app.get("/sender")
    async def which(found=Depends(get_email_sender)):
        return {"same": found is sender}

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/sender")

    assert asyncio.run(go()).json() == {"same": True}


def test_the_identitys_email_comes_first_then_address_for(role_settings):  # noqa: F811
    app, _, _ = _app(role_settings)
    assert asyncio.run(recipient_address(app, _identity("bob", "bob@work.example"))) == (
        "bob@work.example")
    assert asyncio.run(recipient_address(app, _identity("bob"))) == "bob@example.com"
    assert asyncio.run(recipient_address(app, "bob")) == "bob@example.com"
    assert asyncio.run(recipient_address(app, "nobody")) is None


# ── notify by email ────────────────────────────────────────────────────────


@pytest.mark.parametrize(("choice", "stored", "emailed"), [
    ("email", False, True), ("both", True, True), ("in_app", True, False), ("off", False, False),
])
def test_notify_follows_the_preference(role_settings, choice, stored, emailed):  # noqa: F811
    app, store, sender = _app(role_settings, choice=choice, base_url="https://pyfinbot.example")
    result = asyncio.run(notify(app, "bob", PAYLOAD, category="sync"))
    assert (result is not None) is stored
    assert len(store.list_for_sync("bob")) == (1 if stored else 0)
    assert len(sender.outbox) == (1 if emailed else 0)
    if emailed:
        (message,) = sender.outbox
        assert message.to == ("bob@example.com",)
        assert message.subject == "ASX sync finished"
        assert message.text == ("ASX sync finished\n\n"
                                "Open stocks: https://pyfinbot.example/stocks")


def test_the_title_is_the_subject_and_a_long_message_is_cut(role_settings):  # noqa: F811
    app, _, sender = _app(role_settings, choice="email")
    asyncio.run(notify(app, "bob", {"message": "Done", "title": "Sync"}, category="sync"))
    asyncio.run(notify(app, "bob", {"message": "x" * 100}, category="sync"))
    first, second = sender.outbox
    assert first.subject == "Sync" and first.text == "Done"
    assert len(second.subject) == 80 and second.subject.endswith("…")


def test_a_mail_failure_is_logged_and_the_notice_still_stored(role_settings, caplog):  # noqa: F811
    app, store, _ = _app(role_settings, sender=_Failing(), choice="both")
    with caplog.at_level(logging.WARNING, logger="greentechhub_fastapi.notifications"):
        result = asyncio.run(notify(app, "bob", PAYLOAD, category="sync"))
    assert result is not None and len(store.list_for_sync("bob")) == 1
    assert "not emailed to bob" in caplog.text and "smtp.example.com" in caplog.text


def test_no_address_or_no_register_email_sends_nothing(role_settings, caplog):  # noqa: F811
    app, _, sender = _app(role_settings, choice="email")
    with caplog.at_level(logging.WARNING, logger="greentechhub_fastapi.notifications"):
        assert asyncio.run(notify(app, "alice", PAYLOAD, category="sync")) is None
    assert sender.outbox == [] and "no email address for alice" in caplog.text
    bare, _, _ = _app(role_settings, choice="email", email=False)
    assert asyncio.run(notify(bare, "bob", PAYLOAD, category="sync")) is None
