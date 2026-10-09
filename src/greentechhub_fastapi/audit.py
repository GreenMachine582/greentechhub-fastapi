"""audit — the route-local counterparts to registration.audit.register_audit:
writing greentechhub-core's audit log (AuditStore) from a request, and an
admin page that reads it.

- audit(request, action, ...): record one AuditEntry, with the signed-in
  user as its actor unless one is given. Does nothing until register_audit
  ran, so this package's views call it unconditionally and a service that
  never registers audit pays nothing. A store that fails is logged, not
  raised: the action it records has already happened.
- get_audit_store(request): the store register_audit put on the app, or None.
- AuditViews: GET {url}, newest entries first, filtered by actor, action
  (exact, or a prefix ending in ".") and an "on or before" date, paged back
  with a `before` cursor. Gated on a permission the service supplies, like
  RoleAdminViews. Renders greentechhub-ui's audit_page.html by default,
  passing data only.

The views here record their own events: auth.signed_in, auth.sign_in_failed
and auth.locked_out (LoginViews; locked_out is both the failure that trips
the throttle and each attempt refused while it holds), auth.password_changed (SettingsViews),
auth.password_reset (PasswordResetViews), roles.granted and roles.revoked
(RoleAdminViews), and settings.changed (SettingsViews: the keys that
changed, never their values).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.audit import AuditEntry, AuditStore, new_entry
from greentechhub_core.identity import Identity

from greentechhub_fastapi.permissions import require_page_permission

AUDIT_STATE_KEY = "gth_audit"

logger = logging.getLogger(__name__)

_UNSET: Any = object()


@dataclass(frozen=True)
class AuditConfig:
    store: AuditStore
    url: str | None = None


def get_audit_store(request: Request) -> AuditStore | None:
    """The AuditStore register_audit installed, or None."""
    config = getattr(request.app.state, AUDIT_STATE_KEY, None)
    return config.store if config is not None else None


async def audit(
    request: Request,
    action: str,
    *,
    actor: str | None = _UNSET,
    target: tuple[str, Any] | None = None,
    summary: str = "",
    details: Mapping[str, Any] | None = None,
) -> AuditEntry | None:
    """Record `action` (dotted lowercase words, e.g. "stock.archived") and
    return the entry, or None when audit isn't registered. `actor` defaults
    to the signed-in user's subject (None when nobody is); pass it, or None
    for the system, to say otherwise. `target` is (type, id); `details` is
    scrubbed of credential-like keys by core."""
    store = get_audit_store(request)
    if store is None:
        return None
    if actor is _UNSET:
        # Imported here: settings imports auth, whose views import this module.
        from greentechhub_fastapi.settings import _resolve_user

        user = await _resolve_user(request)
        actor = user.subject if user is not None else None
    entry = new_entry(action, actor=actor, target=target, summary=summary, details=details)
    try:
        await store.record(entry)
    except Exception:
        logger.exception("audit: recording %s failed", action)
        return None
    return entry


def _day(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _when(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class AuditViews:
    """The audit log admin page. Mount it like RoleAdminViews, or pass it to
    register_audit(..., views=):
    `AuditViews(templates=templates, permission="audit.view")`.

    GET {url}?actor=&action=&on_or_before=YYYY-MM-DD&before=<cursor>: up to
    `page_size` entries, newest first. `before` (an entry's ISO time) pages
    back; the context carries the next page's URL while there may be more.
    An unreadable date or cursor is ignored rather than refused.
    """

    page_template: str = "audit_page.html"
    url: str = "/admin/audit"
    login_url: str = "/login"
    title: str = "Audit log"
    page_size: int = 50

    def __init__(self, *, templates: Jinja2Templates, permission: str) -> None:
        self._templates = templates
        self._guard = require_page_permission(permission, self.login_url)

    def router(self) -> APIRouter:
        router = APIRouter()

        async def page(request: Request, user: Identity = Depends(self._guard)):
            return self._templates.TemplateResponse(
                request, self.page_template,
                {"page_title": self.title, **await self._context(request)},
            )

        router.add_api_route(self.url, page, methods=["GET"])
        return router

    async def _context(self, request: Request) -> dict[str, Any]:
        query = request.query_params
        actor = (query.get("actor") or "").strip()
        action = (query.get("action") or "").strip().lower()
        day = _day((query.get("on_or_before") or "").strip())
        cursor = _when((query.get("before") or "").strip())
        if day is not None:
            end_of_day = datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)
            cursor = min(cursor, end_of_day) if cursor is not None else end_of_day

        filters = {"actor": actor, "action": action,
                   "on_or_before": day.isoformat() if day else ""}
        entries: list[AuditEntry] = []
        store = get_audit_store(request)
        if store is not None:
            entries = await store.entries(
                actor=actor or None, action=action or None, before=cursor,
                limit=self.page_size,
            )
        next_url = None
        if len(entries) == self.page_size:
            params = {k: v for k, v in filters.items() if v}
            next_url = f"{self.url}?{urlencode({**params, 'before': entries[-1].at.isoformat()})}"
        return {
            "audit_url": self.url,
            "audit_filters": filters,
            "audit_entries": [self._row(entry) for entry in entries],
            "audit_next_url": next_url,
        }

    @staticmethod
    def _row(entry: AuditEntry) -> dict[str, Any]:
        target = None
        if entry.target_type is not None:
            target = f"{entry.target_type}:{entry.target_id}"
        return {"at": entry.at, "actor": entry.actor, "action": entry.action,
                "target": target, "summary": entry.summary, "details": dict(entry.details)}
