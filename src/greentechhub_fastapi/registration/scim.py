"""register_scim — mount the inbound SCIM 2.0 Users endpoint (scim.py) over
register_users' UserStore."""

from fastapi import FastAPI

from greentechhub_fastapi.scim import ScimViews


def register_scim(
    app: FastAPI, *, token: str, provider: str = "authentik", prefix: str = "/scim/v2"
) -> ScimViews:
    """Mount SCIM at `prefix`, accepting `Authorization: Bearer <token>`,
    and return the views. Pushed accounts are linked under `provider`.
    Needs register_users (a request without it fails with RuntimeError).
    Raises ValueError for an empty token."""
    views = ScimViews(token=token, provider=provider, prefix=prefix)
    app.include_router(views.router())
    return views
