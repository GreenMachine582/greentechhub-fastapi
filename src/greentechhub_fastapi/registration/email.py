"""register_email — puts a greentechhub-core EmailSender on the app for
send_email() and notify()'s email channel.

Opt-in like every register_* call. The usual sender is core's
SettingsEmailSender, which reads the mail server from core's smtp_settings
(the password a secret setting) on every send, so an admin sets it up on
the settings page:

    registry = SettingsRegistry([..., *smtp_settings(edit_permission="settings.manage")])
    service = register_settings(app, settings, registry=registry, store=store,
                                cipher=settings_cipher(settings))
    register_email(app, settings, sender=SettingsEmailSender(service),
                   base_url="https://pyfinbot.example")

InMemoryEmailSender keeps an outbox instead, for development and tests.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI
from greentechhub_core.email import EmailSender

from greentechhub_fastapi.email import EMAIL_STATE_KEY, EmailConfig


def register_email(
    app: FastAPI,
    settings: Any,
    *,
    sender: EmailSender,
    address_for: Callable[[str], Awaitable[str | None]] | None = None,
    base_url: str | None = None,
) -> EmailSender:
    """Install the app's EmailSender and return it. `settings` is the
    service's GTHBaseSettings, accepted for symmetry with the other
    register_* calls.

    `address_for(subject)` looks up a person's address when notify() has
    only a subject, or an Identity without an email (e.g. from the
    service's users table). `base_url` makes relative links in emails
    absolute, e.g. a notification's action link."""
    if app.middleware_stack is not None:
        raise RuntimeError("register_email must run before the app starts")
    setattr(app.state, EMAIL_STATE_KEY,
            EmailConfig(sender=sender, address_for=address_for, base_url=base_url))
    return sender
