"""register_audit — puts greentechhub-core's AuditStore on the app for
audit(), and optionally mounts the audit log page.

Opt-in like every register_* call. It:
  - stores the AuditStore on app.state, where audit() and get_audit_store
    find it — from then on this package's views record their own events
    (sign-ins, password changes, role grants, settings changes);
  - mounts `views` (an AuditViews) when given.

A database-backed log is core's SQLAlchemyAuditStore over gth_audit_log;
InMemoryAuditStore suits tests.
"""

from typing import Any

from fastapi import FastAPI
from greentechhub_core.audit import AuditStore

from greentechhub_fastapi.audit import AUDIT_STATE_KEY, AuditConfig, AuditViews


def register_audit(
    app: FastAPI,
    settings: Any,
    *,
    store: AuditStore,
    views: AuditViews | None = None,
) -> AuditStore:
    """Install the app's AuditStore and return it. `settings` is the
    service's GTHBaseSettings, accepted for symmetry with the other
    register_* calls."""
    if app.middleware_stack is not None:
        raise RuntimeError("register_audit must run before the app starts")
    setattr(app.state, AUDIT_STATE_KEY,
            AuditConfig(store=store, url=views.url if views is not None else None))
    if views is not None:
        app.include_router(views.router())
    return store
