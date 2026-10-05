"""notifications — the per-request and route-level side of
registration.notifications.register_notifications, over greentechhub-core's
NotificationStore.

- notify: store a notice for one person, built from a greentechhub-ui
  toast() payload, honouring their delivery preference for its category
  (core's notification_preferences, when register_settings has them), and
  email it when they chose email and register_email ran.
- NotificationViews: the signed-in user's notifications page, a panel
  partial for a navbar dropdown, a live badge (gth_nav_badge's badge_url)
  and the mark-read / mark-all-read actions. Like SettingsViews it renders
  greentechhub-ui templates by name, passing data only: nothing here imports
  greentechhub-ui.
- notifications_nav_item: a NavItem whose badge shows the unread count and
  refreshes whenever a notification is marked read (NOTIFICATIONS_EVENT).

Every route acts for the signed-in user only: the recipient is always
`user.subject`, and core's mark_read never touches someone else's notices.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import EmailDeliveryError, EmailNotConfiguredError, new_email
from greentechhub_core.identity import Identity
from greentechhub_core.notifications import (
    Notification,
    NotificationStore,
    channels_for,
    from_toast,
)

from greentechhub_fastapi.auth.dependency import get_current_user
from greentechhub_fastapi.dependencies.identity import require_page_identity
from greentechhub_fastapi.email import (
    EMAIL_STATE_KEY,
    absolute_url,
    recipient_address,
    send_email,
)

logger = logging.getLogger(__name__)

NOTIFICATIONS_STATE_KEY = "gth_notifications"

NOTIFICATIONS_EVENT = "gth:notifications"
"""The HX-Trigger event every mark-read answer fires, with {"unread": n}:
a badge (notifications_nav_item) or panel listening for it refreshes."""


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationsConfig:
    """What register_notifications put on app.state."""

    store: NotificationStore
    url: str | None  # NotificationViews' mount path, when register_notifications mounted them


def get_notifications_config(app: Any) -> NotificationsConfig:
    config = getattr(app.state, NOTIFICATIONS_STATE_KEY, None)
    if config is None:
        raise RuntimeError("no notification store: call register_notifications(app, ...) first")
    return config


def get_notification_store(request: Request) -> NotificationStore:
    """The NotificationStore register_notifications installed (a Depends() helper)."""
    return get_notifications_config(request.app).store


@dataclass(frozen=True, slots=True)
class _Subject:
    subject: str


async def notify(
    app: Any,
    recipient: Identity | str,
    payload: dict[str, Any],
    *,
    category: str = "general",
) -> Notification | None:
    """Deliver a notice to `recipient` (an Identity, or a subject for code
    with no Identity at hand, such as a scheduled job): store it for the
    notification centre and/or email it. Returns the stored Notification, or
    None when it wasn't stored (the person chose email only, or off).

    `payload` is a greentechhub-ui toast() detail, or the whole
    {"showToast": ...} value toast() returns. When register_settings has
    core's notification_preferences for `category`, the person's choice
    decides the channels; otherwise it's in-app only.

    The email channel needs register_email and an address (the Identity's
    email, else register_email's address_for). The email's subject is the
    title, else the message; its text is the message plus the action link,
    made absolute with base_url. A failed or unconfigured send, or a missing
    address, is logged as a warning and never raised: a mail problem mustn't
    break the in-app notice or the caller.
    """
    store = get_notifications_config(app).store
    subject = recipient if isinstance(recipient, str) else recipient.subject
    # Imported here: greentechhub_fastapi.settings imports auth.dependency,
    # whose package __init__ imports the auth views.
    from greentechhub_fastapi.settings import SETTINGS_STATE_KEY

    settings_config = getattr(app.state, SETTINGS_STATE_KEY, None)
    channels: frozenset[str] = frozenset({"in_app"})
    if settings_config is not None:
        channels = await channels_for(settings_config.settings, _Subject(subject), category)
    notification = from_toast(subject, payload, category=category)
    if "email" in channels and getattr(app.state, EMAIL_STATE_KEY, None) is not None:
        await _email_notification(app, recipient, notification)
    if "in_app" not in channels:
        return None
    await store.add(notification)
    return notification


async def _email_notification(app: Any, recipient: Identity | str,
                              notification: Notification) -> None:
    address = await recipient_address(app, recipient)
    if address is None:
        logger.warning("no email address for %s; notification %s not emailed",
                       notification.recipient, notification.id)
        return
    message = notification.message
    subject = notification.title or (message if len(message) <= 80 else message[:79] + "…")
    text = message
    if notification.action_label and notification.action_url:
        text += f"\n\n{notification.action_label}: {absolute_url(app, notification.action_url)}"
    try:
        await send_email(app, new_email(address, subject, text))
    except (EmailDeliveryError, EmailNotConfiguredError, ValueError) as exc:
        logger.warning("notification %s not emailed to %s: %s",
                       notification.id, notification.recipient, exc)


def notifications_nav_item(
    url: str = "/notifications", label: str = "Notifications", icon: str = "bell"
) -> dict[str, Any]:
    """A greentechhub-ui NavItem for the notifications page whose badge is the
    live unread count: fetched from `{url}/badge` and fetched again on
    NOTIFICATIONS_EVENT."""
    return {"label": label, "url": url, "icon": icon, "badge_url": f"{url}/badge",
            "badge_event": NOTIFICATIONS_EVENT}


def _local_path(value: object) -> str | None:
    """`value` when it's a path on this site, else None (never an open redirect)."""
    if isinstance(value, str) and value.startswith("/") and not value.startswith(("//", "/\\")):
        return value
    return None


class NotificationViews:
    """The notification centre's routes. Pass an instance to
    `register_notifications(..., views=NotificationViews(templates=templates))`,
    which mounts it at `url`.

    GET {url}: the user's notifications, newest first, at most page_size;
    `?unread=1` shows only unread ones. Anonymous visitors go to login_url.
    GET {url}/panel: the newest panel_size, as a partial for a dropdown.
    GET {url}/badge: the unread count for gth_nav_badge's badge_url (204 for
    an anonymous visitor).
    POST {url}/{id}/read and {url}/read-all: mark them read and answer 204
    with HX-Trigger {NOTIFICATIONS_EVENT: {"unread": n}}; a local `next`
    form field redirects there (303) instead, for a form without htmx.

    Templates get, on the page and panel: {"page_title", "notifications",
    "unread_count", "unread_only", "page_url", "mark_all_url"}, each
    notification a dict of its fields plus "read", "read_url" and "toast"
    (its toast() detail); the badge gets {"count"} and should render nothing
    for 0. They default to greentechhub-ui's notification centre templates;
    override the names to use your own.
    """

    page_template: str = "notifications_page.html"
    panel_template: str = "notifications_panel.html"
    badge_template: str = "notification_badge.html"
    url: str = "/notifications"
    login_url: str = "/login"
    title: str = "Notifications"
    page_size: int = 50
    panel_size: int = 10

    def __init__(self, *, templates: Jinja2Templates) -> None:
        self._templates = templates
        self._page_identity = require_page_identity(self.login_url)

    def router(self) -> APIRouter:
        router = APIRouter()
        page_identity = self._page_identity

        async def page(request: Request, user: Identity = Depends(page_identity)):
            unread_only = request.query_params.get("unread") in ("1", "true")
            return await self._render(request, user, self.page_template, self.page_size,
                                      unread_only=unread_only)

        async def panel(request: Request, user: Identity = Depends(page_identity)):
            return await self._render(request, user, self.panel_template, self.panel_size)

        async def badge(request: Request, user: Identity | None = Depends(get_current_user)):
            if user is None:
                return Response(status_code=204)
            count = await get_notification_store(request).unread_count(user.subject)
            return self._templates.TemplateResponse(request, self.badge_template, {"count": count})

        async def read_one(
            request: Request, notification_id: str, user: Identity = Depends(page_identity)
        ):
            store = get_notification_store(request)
            await store.mark_read(user.subject, [notification_id], at=datetime.now(UTC))
            return await self._marked(request, user)

        async def read_all(request: Request, user: Identity = Depends(page_identity)):
            store = get_notification_store(request)
            await store.mark_all_read(user.subject, at=datetime.now(UTC))
            return await self._marked(request, user)

        router.add_api_route(self.url, page, methods=["GET"])
        router.add_api_route(f"{self.url}/panel", panel, methods=["GET"])
        router.add_api_route(f"{self.url}/badge", badge, methods=["GET"])
        router.add_api_route(f"{self.url}/read-all", read_all, methods=["POST"])
        router.add_api_route(f"{self.url}/{{notification_id}}/read", read_one, methods=["POST"])
        return router

    def _item(self, notification: Notification) -> dict[str, Any]:
        return {
            "id": notification.id,
            "message": notification.message,
            "kind": notification.kind,
            "title": notification.title,
            "icon": notification.icon,
            "action_label": notification.action_label,
            "action_url": notification.action_url,
            "category": notification.category,
            "created_at": notification.created_at,
            "read_at": notification.read_at,
            "read": notification.read,
            "read_url": f"{self.url}/{notification.id}/read",
            "toast": notification.to_toast(),
        }

    async def _render(
        self, request: Request, user: Identity, template: str, limit: int, *,
        unread_only: bool = False,
    ):
        store = get_notification_store(request)
        notifications = await store.list_for(user.subject, unread_only=unread_only, limit=limit)
        return self._templates.TemplateResponse(request, template, {
            "page_title": self.title,
            "notifications": [self._item(n) for n in notifications],
            "unread_count": await store.unread_count(user.subject),
            "unread_only": unread_only,
            "page_url": self.url,
            "mark_all_url": f"{self.url}/read-all",
        })

    async def _marked(self, request: Request, user: Identity) -> Response:
        form = await request.form()
        if (next_url := _local_path(form.get("next"))) is not None:
            return RedirectResponse(next_url, status_code=303)
        unread = await get_notification_store(request).unread_count(user.subject)
        trigger = json.dumps({NOTIFICATIONS_EVENT: {"unread": unread}})
        return Response(status_code=204, headers={"HX-Trigger": trigger})
