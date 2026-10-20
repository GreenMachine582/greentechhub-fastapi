"""scim — an inbound SCIM 2.0 Users endpoint (RFC 7643/7644) over the
UserStore register_users installed, so an IdP pushes account changes the
moment they happen: Authentik's SCIM provider creates, updates and
deactivates people here without waiting for them to sign in, and retries
and periodically re-syncs on its own, so no service needs a reconciliation
job.

    register_users(app, store)
    register_scim(app, token=settings.scim_token)   # Authentik: SCIM provider → this URL + token

Mounted at `prefix` (default /scim/v2):
  GET    /ServiceProviderConfig, /ResourceTypes, /Schemas
  GET    /Users                  ?filter=userName eq "x" | externalId eq "x", startIndex, count
  POST   /Users                  create; externalId links the IdP's id to the account
  GET    /Users/{id}
  PUT    /Users/{id}             replace userName, displayName, emails, active
  PATCH  /Users/{id}             add/replace/remove on those paths (or a path-less value object)
  DELETE /Users/{id}             deactivates — the account and its rows stay

Every request needs `Authorization: Bearer <token>` (compared in constant
time); without it, 401. Groups aren't synced (roles come from the
forward-auth groups header and ROLE_GROUPS): /Groups answers 501, so set
the IdP's SCIM provider to users only.

`externalId` is the IdP's immutable id for the person — for Authentik it
must be the user's `uid`, the same value its outpost sends as
X-authentik-uid, so a pushed account and a forward-auth sign-in land on the
same link. Addresses an IdP pushes count as verified.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from greentechhub_core.security import constant_time_compare
from greentechhub_core.users import LinkExists, UserAccount, UserExists, UserStore

from greentechhub_fastapi.auth.accounts import get_user_store

SCIM_MEDIA_TYPE = "application/scim+json"
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
_CONFIG_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
_RESOURCE_TYPE_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
_MAX_COUNT = 200


class ScimError(Exception):
    """A SCIM error response: `status`, an optional `scim_type`
    (uniqueness, invalidFilter, invalidValue, ...) and a detail."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def response(self) -> JSONResponse:
        body: dict[str, Any] = {"schemas": [ERROR_SCHEMA], "status": str(self.status),
                                "detail": self.detail}
        if self.scim_type:
            body["scimType"] = self.scim_type
        return JSONResponse(body, status_code=self.status, media_type=SCIM_MEDIA_TYPE)


def _scim(body: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status_code, media_type=SCIM_MEDIA_TYPE)


def _primary_email(emails: Any) -> str | None:
    """The primary (else first) value of a SCIM emails list."""
    if not isinstance(emails, list) or not emails:
        return None
    entries = [e for e in emails if isinstance(e, Mapping) and e.get("value")]
    if not entries:
        return None
    primary = next((e for e in entries if e.get("primary")), entries[0])
    return str(primary["value"])


def _display_name(resource: Mapping[str, Any]) -> str | None:
    if resource.get("displayName"):
        return str(resource["displayName"])
    name = resource.get("name")
    if isinstance(name, Mapping):
        formatted = name.get("formatted") or " ".join(
            str(name[part]) for part in ("givenName", "familyName") if name.get(part)
        )
        return formatted or None
    return None


def _changes(resource: Mapping[str, Any], *, replace: bool) -> dict[str, Any]:
    """Account changes from a SCIM User resource. With `replace` (PUT), an
    attribute the resource leaves out is cleared (active stays as is)."""
    changes: dict[str, Any] = {}
    if "userName" in resource:
        changes["username"] = str(resource["userName"])
    if replace or "displayName" in resource or "name" in resource:
        changes["display_name"] = _display_name(resource)
    if replace or "emails" in resource:
        changes["email"] = _primary_email(resource.get("emails"))
        changes["email_verified"] = changes["email"] is not None
    if "active" in resource:
        changes["active"] = _boolean(resource["active"])
    return changes


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise ScimError(400, f"{value!r} isn't a boolean", "invalidValue")


def _patch_changes(operations: Any) -> tuple[dict[str, Any], str | None]:
    """Account changes, and a new externalId if any, from PatchOp Operations."""
    if not isinstance(operations, list):
        raise ScimError(400, "Operations must be a list", "invalidSyntax")
    resource: dict[str, Any] = {}
    for operation in operations:
        if not isinstance(operation, Mapping):
            raise ScimError(400, "each operation is an object", "invalidSyntax")
        op = str(operation.get("op", "")).lower()
        if op not in ("add", "replace", "remove"):
            raise ScimError(400, f"unsupported op {operation.get('op')!r}", "invalidSyntax")
        path = operation.get("path")
        value = None if op == "remove" else operation.get("value")
        if not path:
            if not isinstance(value, Mapping):
                raise ScimError(400, "a path-less operation needs an object value",
                                "invalidSyntax")
            resource.update(value)
            continue
        path = str(path)
        if path in ("userName", "displayName", "active", "externalId", "emails"):
            resource[path] = value
        elif path == "name.formatted":
            resource["displayName"] = value
        elif path.startswith("emails"):
            resource["emails"] = [{"value": value, "primary": True}] if value else []
        else:
            raise ScimError(400, f"unsupported path {path!r}", "invalidPath")
    external_id = resource.pop("externalId", None)
    if resource.get("userName") is None:
        resource.pop("userName", None)
    return _changes(resource, replace=False), external_id


def _parse_filter(text: str) -> tuple[str, str]:
    """(attribute, value) from `userName eq "x"` or `externalId eq "x"`."""
    attribute, _, rest = text.strip().partition(" ")
    operator, _, value = rest.strip().partition(" ")
    value = value.strip()
    if (attribute not in ("userName", "externalId") or operator.lower() != "eq"
            or len(value) < 2 or value[0] != '"' or value[-1] != '"'):
        raise ScimError(400, 'only userName eq "..." and externalId eq "..." are supported',
                        "invalidFilter")
    return attribute, value[1:-1]


class ScimViews:
    """The SCIM 2.0 routes; `register_scim` builds and mounts one.

    Args:
        token: the bearer token the IdP sends (a long random secret).
        provider: the Identity.provider pushed accounts are linked under —
            "authentik" to match AuthentikIdentityProvider's default.
        prefix: where the routes are mounted.
    """

    def __init__(self, *, token: str, provider: str = "authentik",
                 prefix: str = "/scim/v2") -> None:
        if not token:
            raise ValueError("register_scim needs a token")
        self._token = token
        self.provider = provider
        self.prefix = prefix.rstrip("/")

    # plumbing

    def _authorized(self, request: Request) -> bool:
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and constant_time_compare(value.strip(), self._token)

    def _location(self, request: Request, user_id: str) -> str:
        return str(request.url_for("scim_user", user_id=user_id))

    async def _resource(self, store: UserStore, request: Request,
                        account: UserAccount) -> dict[str, Any]:
        links = [link for link in await store.links_for(account.id)
                 if link.provider == self.provider]
        resource: dict[str, Any] = {
            "schemas": [USER_SCHEMA],
            "id": account.id,
            "userName": account.username,
            "active": account.active,
            "meta": {
                "resourceType": "User",
                "created": account.created_at.isoformat(),
                "lastModified": account.updated_at.isoformat(),
                "location": self._location(request, account.id),
            },
        }
        if links:
            resource["externalId"] = links[0].external_subject
        if account.display_name:
            resource["displayName"] = account.display_name
            resource["name"] = {"formatted": account.display_name}
        if account.email:
            resource["emails"] = [{"value": account.email, "primary": True, "type": "work"}]
        return resource

    async def _account(self, store: UserStore, user_id: str) -> UserAccount:
        account = await store.get(user_id)
        if account is None:
            raise ScimError(404, f"no user {user_id}")
        return account

    async def _relink(self, store: UserStore, account: UserAccount,
                      external_id: str | None) -> None:
        """Point this provider's link for `account` at `external_id`."""
        if not external_id:
            return
        current = [link for link in await store.links_for(account.id)
                   if link.provider == self.provider]
        if any(link.external_subject == external_id for link in current):
            return
        try:
            await store.link(account.id, self.provider, external_id)
        except LinkExists as exc:
            raise ScimError(409, f"externalId {external_id} belongs to another user",
                            "uniqueness") from exc
        for link in current:
            await store.unlink(self.provider, link.external_subject)

    async def _update(self, store: UserStore, account: UserAccount,
                      changes: Mapping[str, Any]) -> UserAccount:
        try:
            updated = await store.update(account.id, changes) if changes else account
        except UserExists as clash:
            raise ScimError(409, str(clash), "uniqueness") from clash
        except ValueError as exc:
            raise ScimError(400, str(exc), "invalidValue") from exc
        if updated is None:
            raise ScimError(404, f"no user {account.id}")
        return updated

    async def _audit(self, request: Request, action: str, account: UserAccount) -> None:
        from greentechhub_fastapi.audit import audit

        await audit(request, action, actor=None, target=("user", account.id),
                    summary=f"{account.name} {action.split('.')[-1]} by SCIM",
                    details={"provider": self.provider})

    # routes

    def router(self) -> APIRouter:
        router = APIRouter(prefix=self.prefix)
        views = self

        async def guard(request: Request, handler, *args):
            if not views._authorized(request):
                return ScimError(401, "a valid bearer token is required").response()
            try:
                return await handler(request, get_user_store(request), *args)
            except ScimError as error:
                return error.response()

        @router.get("/ServiceProviderConfig")
        async def config(request: Request):
            return await guard(request, views._config)

        @router.get("/ResourceTypes")
        async def resource_types(request: Request):
            return await guard(request, views._resource_types)

        @router.get("/Schemas")
        async def schemas(request: Request):
            return await guard(request, views._schemas)

        @router.get("/Users")
        async def list_users(request: Request):
            return await guard(request, views._list)

        @router.post("/Users")
        async def create_user(request: Request):
            return await guard(request, views._create)

        @router.get("/Users/{user_id}", name="scim_user")
        async def get_user(request: Request, user_id: str):
            return await guard(request, views._get, user_id)

        @router.put("/Users/{user_id}")
        async def replace_user(request: Request, user_id: str):
            return await guard(request, views._replace, user_id)

        @router.patch("/Users/{user_id}")
        async def patch_user(request: Request, user_id: str):
            return await guard(request, views._patch, user_id)

        @router.delete("/Users/{user_id}")
        async def delete_user(request: Request, user_id: str):
            return await guard(request, views._delete, user_id)

        @router.api_route("/Groups", methods=["GET", "POST"])
        @router.api_route("/Groups/{group_id}", methods=["GET", "PUT", "PATCH", "DELETE"])
        async def groups(request: Request, group_id: str | None = None):
            async def refuse(request: Request, store: UserStore):
                raise ScimError(501, "groups aren't synced; roles come from ROLE_GROUPS")

            return await guard(request, refuse)

        return router

    async def _config(self, request: Request, store: UserStore) -> Response:
        unsupported = {"supported": False}
        return _scim({
            "schemas": [_CONFIG_SCHEMA],
            "patch": {"supported": True},
            "bulk": {**unsupported, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": _MAX_COUNT},
            "changePassword": unsupported,
            "sort": unsupported,
            "etag": unsupported,
            "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token",
                                       "description": "Authorization: Bearer <token>"}],
        })

    async def _resource_types(self, request: Request, store: UserStore) -> Response:
        return _scim({"schemas": [LIST_SCHEMA], "totalResults": 1, "Resources": [{
            "schemas": [_RESOURCE_TYPE_SCHEMA], "id": "User", "name": "User",
            "endpoint": "/Users", "schema": USER_SCHEMA,
        }]})

    async def _schemas(self, request: Request, store: UserStore) -> Response:
        attributes = [{"name": name, "type": kind, "multiValued": multi, "required": required}
                      for name, kind, multi, required in (
                          ("userName", "string", False, True),
                          ("displayName", "string", False, False),
                          ("emails", "complex", True, False),
                          ("active", "boolean", False, False))]
        return _scim({"schemas": [LIST_SCHEMA], "totalResults": 1, "Resources": [{
            "id": USER_SCHEMA, "name": "User", "attributes": attributes,
        }]})

    async def _list(self, request: Request, store: UserStore) -> Response:
        params = request.query_params
        try:
            start = max(1, int(params.get("startIndex", 1)))
            count = min(_MAX_COUNT, max(0, int(params.get("count", 100))))
        except ValueError as exc:
            raise ScimError(400, "startIndex and count are integers", "invalidValue") from exc
        if params.get("filter"):
            attribute, value = _parse_filter(params["filter"])
            if attribute == "userName":
                found = await store.by_username(value)
            else:
                link = await store.find_link(self.provider, value)
                found = await store.get(link.user_id) if link else None
            accounts = [found] if found is not None else []
        else:
            accounts = await store.list_users()
        page = accounts[start - 1:start - 1 + count]
        return _scim({
            "schemas": [LIST_SCHEMA],
            "totalResults": len(accounts),
            "startIndex": start,
            "itemsPerPage": len(page),
            "Resources": [await self._resource(store, request, a) for a in page],
        })

    async def _body(self, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError as exc:
            raise ScimError(400, "the body isn't JSON", "invalidSyntax") from exc
        if not isinstance(body, dict):
            raise ScimError(400, "the body is a JSON object", "invalidSyntax")
        return body

    async def _create(self, request: Request, store: UserStore) -> Response:
        body = await self._body(request)
        if not body.get("userName"):
            raise ScimError(400, "userName is required", "invalidValue")
        changes = _changes(body, replace=False)
        external_id = body.get("externalId")
        link = (self.provider, str(external_id)) if external_id else None
        try:
            account = await store.create(
                changes.pop("username"), link=link, auth_source=self.provider,
                email=changes.pop("email", None),
                email_verified=changes.pop("email_verified", False),
                display_name=changes.pop("display_name", None),
            )
        except (UserExists, LinkExists) as clash:
            raise ScimError(409, str(clash), "uniqueness") from clash
        except ValueError as exc:
            raise ScimError(400, str(exc), "invalidValue") from exc
        if changes:
            account = await self._update(store, account, changes)
        await self._audit(request, "user.provisioned", account)
        resource = await self._resource(store, request, account)
        response = _scim(resource, status_code=201)
        response.headers["Location"] = resource["meta"]["location"]
        return response

    async def _get(self, request: Request, store: UserStore, user_id: str) -> Response:
        return _scim(await self._resource(store, request, await self._account(store, user_id)))

    async def _replace(self, request: Request, store: UserStore, user_id: str) -> Response:
        account = await self._account(store, user_id)
        body = await self._body(request)
        if not body.get("userName"):
            raise ScimError(400, "userName is required", "invalidValue")
        await self._relink(store, account, body.get("externalId"))
        account = await self._update(store, account, _changes(body, replace=True))
        await self._audit(request, "user.synced", account)
        return _scim(await self._resource(store, request, account))

    async def _patch(self, request: Request, store: UserStore, user_id: str) -> Response:
        account = await self._account(store, user_id)
        body = await self._body(request)
        changes, external_id = _patch_changes(body.get("Operations"))
        await self._relink(store, account, external_id)
        was_active = account.active
        account = await self._update(store, account, changes)
        action = "user.deactivated" if was_active and not account.active else "user.synced"
        await self._audit(request, action, account)
        return _scim(await self._resource(store, request, account))

    async def _delete(self, request: Request, store: UserStore, user_id: str) -> Response:
        account = await self._update(store, await self._account(store, user_id),
                                     {"active": False})
        await self._audit(request, "user.deactivated", account)
        return Response(status_code=204)
