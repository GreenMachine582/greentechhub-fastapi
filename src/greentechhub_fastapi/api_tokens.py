"""api_tokens — personal API tokens: credentials a person creates in
Settings for their own scripts, which (unlike a login JWT) they can revoke.

    register_auth(app, settings, bearer=True)
    register_api_tokens(app, settings, store=SQLAlchemyApiTokenStore(...))
    register_settings(app, settings, ..., views=SettingsViews(
        templates=templates, api_tokens=ApiTokenViews(templates=templates)))

- register_api_tokens puts greentechhub-core's ApiTokenStore on the app.
  From then on, with register_auth(bearer=True), `Authorization: Bearer
  <personal token>` signs the token's owner in.
- A token's scopes are permission strings, capped by its owner's: it can
  only be created with permissions the owner holds, and each request it
  makes holds only the owner's current permissions that are among its
  scopes (see permissions.resolve_granted).
- ApiTokenViews is the "API tokens" section of SettingsViews' page: create
  one (the plaintext shown this once), list them with last use, revoke.
  A request signed in with a personal token can't do either, so a token
  can't mint more. With register_audit, api_token.created and
  api_token.revoked are recorded (never the token itself).

Renders greentechhub-ui's api_tokens_section.html by default, passing data
only (see ApiTokenViews.section for its context).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import Identity
from greentechhub_core.security import ApiToken

from greentechhub_fastapi.audit import audit
from greentechhub_fastapi.auth.personal_tokens import (
    API_TOKEN_CLAIM,
    get_api_token_store,
    resolve_api_token,
    signed_in_with_api_token,
)
from greentechhub_fastapi.htmx import _toast_trigger
from greentechhub_fastapi.permissions import RESOLVER_STATE_KEY, resolve_granted

__all__ = [
    "API_TOKEN_CLAIM",
    "ApiTokenViews",
    "get_api_token_store",
    "resolve_api_token",
]


class ApiTokenViews:
    """The "API tokens" section of the settings page. Pass an instance to
    `SettingsViews(..., api_tokens=ApiTokenViews(templates=templates))`,
    which adds the section after Password and mounts:

    POST {settings_url}/api-tokens: create one from the form fields `name`,
    `scopes` (repeated; each must be a permission the user holds) and
    `expires_in_days` (one of expiry_days; blank for never when None is
    one). 422 with the section's errors, or 200 with the section carrying
    `created` (the plaintext, this once) and a "Token created" toast.

    DELETE {settings_url}/api-tokens/{id}: revoke one of the user's tokens:
    200 with the section and a "Token revoked" toast, 404 when it isn't
    theirs.

    Both answer 403 to a request signed in with a personal token, and need
    register_api_tokens (RuntimeError otherwise).
    """

    section_template: str = "api_tokens_section.html"
    title: str = "API tokens"
    description: str = (
        "Tokens let your scripts call the API as you. Each one can do only what its scopes "
        "allow, and stops working when you revoke it."
    )
    max_name_length: int = 80
    expiry_days: tuple[int | None, ...] = (30, 90, 365, None)
    default_expiry_days: int | None = 90

    def __init__(self, *, templates: Jinja2Templates) -> None:
        self._templates = templates

    def add_routes(self, router: APIRouter, settings_url: str, page_identity: Any) -> None:
        """Mount the create and revoke routes on SettingsViews' router."""
        url = f"{settings_url}/api-tokens"

        async def create(request: Request, user: Identity = Depends(page_identity)):
            return await self._create(request, user, settings_url)

        async def revoke(request: Request, token_id: str, user: Identity = Depends(page_identity)):
            return await self._revoke(request, user, settings_url, token_id)

        router.add_api_route(url, create, methods=["POST"])
        router.add_api_route(f"{url}/{{token_id}}", revoke, methods=["DELETE"])

    async def section(
        self,
        request: Request,
        user: Identity,
        settings_url: str,
        *,
        created: dict[str, str] | None = None,
        errors: dict[str, list[str]] | None = None,
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The section's context, for settings_sections:

        id ("api_tokens"), title, description, template (section_template),
        action (the create URL); tokens: each token's id, name, scopes
        (sorted), created_at, expires_at, last_used_at, expired and
        revoke_url, newest first; scope_choices: the permissions the user
        may give a token, sorted; expiry_choices and default_expiry_days;
        values: the submitted form after a 422; created: {"name", "token"}
        right after a create; errors: field → messages.
        """
        tokens = await self._store(request).list_for(user.subject)
        now = datetime.now(UTC)
        url = f"{settings_url}/api-tokens"
        return {
            "id": "api_tokens",
            "title": self.title,
            "description": self.description,
            "template": self.section_template,
            "action": url,
            "tokens": [self._token(token, url, now) for token in tokens],
            "scope_choices": sorted(await self._grantable(request, user)),
            "expiry_choices": list(self.expiry_days),
            "default_expiry_days": self.default_expiry_days,
            "values": values or {},
            "created": created,
            "errors": errors,
        }

    @staticmethod
    def _token(token: ApiToken, url: str, now: datetime) -> dict[str, Any]:
        return {
            "id": token.id,
            "name": token.name,
            "scopes": sorted(token.scopes),
            "created_at": token.created_at,
            "expires_at": token.expires_at,
            "last_used_at": token.last_used_at,
            "expired": not token.active(now),
            "revoke_url": f"{url}/{token.id}",
        }

    @staticmethod
    def _store(request: Request):
        store = get_api_token_store(request)
        if store is None:
            raise RuntimeError("ApiTokenViews needs register_api_tokens(app, ..., store=...)")
        return store

    @staticmethod
    async def _grantable(request: Request, user: Identity) -> frozenset[str]:
        resolver = getattr(request.app.state, RESOLVER_STATE_KEY, None)
        if resolver is None:
            return frozenset()
        return frozenset(str(p) for p in await resolve_granted(request, user, resolver))

    def _expiry(self, raw: str) -> tuple[bool, int | None]:
        """(valid, days) for the submitted expires_in_days."""
        raw = raw.strip()
        if not raw:
            return None in self.expiry_days, None
        try:
            days = int(raw)
        except ValueError:
            return False, None
        return days in self.expiry_days, days

    async def _create(self, request: Request, user: Identity, settings_url: str):
        if signed_in_with_api_token(request):
            return Response(status_code=403)
        store = self._store(request)
        form = await request.form()
        name = str(form.get("name") or "").strip()
        scopes = sorted({str(s) for s in form.getlist("scopes") if str(s)})
        raw_expiry = str(form.get("expires_in_days") or "")
        errors: dict[str, list[str]] = {}
        if not name:
            errors["name"] = ["Give the token a name."]
        elif len(name) > self.max_name_length:
            errors["name"] = [f"At most {self.max_name_length} characters."]
        not_yours = [s for s in scopes if s not in await self._grantable(request, user)]
        if not_yours:
            errors["scopes"] = [f"You can't give a token {', '.join(not_yours)}."]
        valid, days = self._expiry(raw_expiry)
        if not valid:
            errors["expires_in_days"] = ["Choose one of the offered expiries."]
        if errors:
            values = {"name": name, "scopes": scopes, "expires_in_days": raw_expiry}
            section = await self.section(request, user, settings_url, errors=errors, values=values)
            return self._render(request, section, status_code=422)

        expires_at = datetime.now(UTC) + timedelta(days=days) if days is not None else None
        token, plaintext = await store.create(user.subject, name, scopes, expires_at)
        await audit(request, "api_token.created", actor=user.subject,
                    target=("api_token", token.id), summary=f"Created API token {name!r}",
                    details={"name": name, "scopes": scopes})
        section = await self.section(request, user, settings_url,
                                     created={"name": name, "token": plaintext})
        return self._render(request, section,
                            headers={"HX-Trigger": _toast_trigger("Token created", {})})

    async def _revoke(self, request: Request, user: Identity, settings_url: str, token_id: str):
        if signed_in_with_api_token(request):
            return Response(status_code=403)
        if not await self._store(request).revoke(token_id, owner=user.subject):
            return Response(status_code=404)
        await audit(request, "api_token.revoked", actor=user.subject,
                    target=("api_token", token_id), summary="Revoked an API token")
        section = await self.section(request, user, settings_url)
        return self._render(request, section,
                            headers={"HX-Trigger": _toast_trigger("Token revoked", {})})

    def _render(self, request: Request, section: dict[str, Any], **kwargs):
        return self._templates.TemplateResponse(
            request, self.section_template, {"section": section}, **kwargs
        )
