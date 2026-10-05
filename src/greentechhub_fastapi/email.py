"""email — the route-level side of registration.email.register_email, over
greentechhub-core's EmailSender.

- send_email: send one core EmailMessage through the registered sender,
  for a service's own routes and jobs (password reset, exports, ...).
  Errors propagate: EmailDeliveryError / EmailNotConfiguredError are core
  ApplicationErrors, which the exception handlers answer 502 / 503.
- get_email_sender: the same sender as a Depends() helper.
- recipient_address: where to email a person — their Identity's email,
  else the service's `address_for` lookup.

notifications.notify uses these for the "email" delivery channel.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from fastapi import Request
from greentechhub_core.email import EmailMessage, EmailSender
from greentechhub_core.identity import Identity

EMAIL_STATE_KEY = "gth_email"


@dataclass(frozen=True, slots=True, kw_only=True)
class EmailConfig:
    """What register_email put on app.state."""

    sender: EmailSender
    address_for: Callable[[str], Awaitable[str | None]] | None = None
    base_url: str | None = None


def get_email_config(app: Any) -> EmailConfig:
    config = getattr(app.state, EMAIL_STATE_KEY, None)
    if config is None:
        raise RuntimeError("no email sender: call register_email(app, ...) first")
    return config


def get_email_sender(request: Request) -> EmailSender:
    """The EmailSender register_email installed (a Depends() helper)."""
    return get_email_config(request.app).sender


async def send_email(app: Any, message: EmailMessage) -> None:
    """Send `message` through the registered sender. EmailDeliveryError /
    EmailNotConfiguredError propagate."""
    await get_email_config(app).sender.send(message)


async def recipient_address(app: Any, recipient: Identity | str) -> str | None:
    """Where to email `recipient` (an Identity or a subject): the Identity's
    email when it has one, else register_email's `address_for(subject)`,
    else None."""
    if isinstance(recipient, Identity) and recipient.email:
        return recipient.email
    address_for = get_email_config(app).address_for
    if address_for is None:
        return None
    subject = recipient if isinstance(recipient, str) else recipient.subject
    return await address_for(subject) or None


def email_looks_valid(address: str) -> bool:
    """Whether `address` looks like an email address: one @ with text on both
    sides and no spaces. A form check, not a delivery guarantee."""
    local, at, domain = address.partition("@")
    return bool(local and at and domain) and "@" not in domain and not any(
        c.isspace() for c in address
    )


def absolute_url(app: Any, url: str) -> str:
    """`url` made absolute with register_email's `base_url`, for a link in an
    email; returned as given without a base_url or when already absolute."""
    base_url = get_email_config(app).base_url
    if not base_url or "://" in url:
        return url
    return urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))
