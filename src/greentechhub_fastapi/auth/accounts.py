"""accounts — turning whatever the auth adapter resolved into the caller's
user account (greentechhub-core's users module), once register_users has
installed a UserStore.

register_auth wraps every adapter's get_current_user with
`with_user_accounts`: the adapter's Identity (a local session JWT, a
personal API token's owner, Authentik's forward-auth headers) goes through
core's resolve_account, and routes receive the account's canonical Identity
instead, whose subject is the account id. So:

  - Authentik sign-ins are provisioned and linked on first use, and the
    fields the IdP owns are kept in step on every request (throttled
    writes; see core's ProvisioningPolicy).
  - Profile fields come from the account, read per request, never from
    whatever a session token carried when it was issued.
  - Deactivating an account signs it out on its next request, sessions and
    personal API tokens alike.

Without register_users nothing changes: the adapter's Identity passes
through as before. The result is cached on request.state, so a page
request that resolves the user several times (the settings middleware,
permissions, the route) resolves it once.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from greentechhub_core.identity import Identity
from greentechhub_core.users import (
    ProvisioningPolicy,
    Resolution,
    UserStore,
    account_identity,
    resolve_account,
)

#: Where register_users keeps its UsersConfig on app.state.
USERS_STATE_KEY = "gth_users"
#: request.state: the resolved Identity (or None), once resolved this request.
_RESOLVED = "gth_user_account_identity"
#: request.state: the Resolution behind it.
_RESOLUTION = "gth_user_account_resolution"

_SUMMARIES = {
    "provisioned": "Account created for {name} on first sign-in through {provider}",
    "linked": "{provider} sign-in linked to {name}",
    "synced": "Profile for {name} updated from {provider}",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class UsersConfig:
    """What register_users put on app.state.

    Fields:
        store: the UserStore.
        policy: core's ProvisioningPolicy for sign-ins from an IdP.
        idp_label: how pages name the IdP whose fields are locked
            ("Managed by {idp_label}").
    """

    store: UserStore
    policy: ProvisioningPolicy
    idp_label: str


def get_users_config(app: Any) -> UsersConfig | None:
    """register_users' config (`app` may be the app or a request), or None."""
    app = getattr(app, "app", app)
    return getattr(app.state, USERS_STATE_KEY, None)


def get_user_store(app: Any) -> UserStore:
    """The UserStore register_users installed. Raises RuntimeError without one."""
    config = get_users_config(app)
    if config is None:
        raise RuntimeError("no user store: call register_users(app, store) first")
    return config.store


def last_resolution(request: Request) -> Resolution | None:
    """How this request's caller was resolved to an account, or None."""
    return getattr(request.state, _RESOLUTION, None)


async def resolve_user(request: Request, external: Identity | None) -> Identity | None:
    """`external`'s account as its canonical Identity, or None when there's
    no account for it (inactive, or unlinked and not provisioned). Returns
    `external` unchanged without register_users. Provisioning, linking and
    syncing are recorded in the audit log, when register_audit ran."""
    config = get_users_config(request)
    if config is None or external is None:
        return external
    resolution = await resolve_account(config.store, external, config.policy)
    setattr(request.state, _RESOLUTION, resolution)
    if resolution is None:
        return None
    if resolution.outcome != "existing":
        await _audit(request, resolution, external)
    return account_identity(resolution.account, external)


async def _audit(request: Request, resolution: Resolution, external: Identity) -> None:
    # Imported here: audit imports permissions, which imports auth.dependency.
    from greentechhub_fastapi.audit import audit

    account = resolution.account
    summary = _SUMMARIES[resolution.outcome].format(name=account.name, provider=external.provider)
    await audit(request, f"user.{resolution.outcome}", actor=account.id,
                target=("user", account.id), summary=summary,
                details={"provider": external.provider})


def with_user_accounts(
    get_user: Callable[[Request], Awaitable[Identity | None]],
) -> Callable[[Request], Awaitable[Identity | None]]:
    """`get_user` (an adapter's get_current_user) resolved through
    register_users' store when the app has one; cached per request."""

    async def _get_current_user(request: Request) -> Identity | None:
        if hasattr(request.state, _RESOLVED):
            return getattr(request.state, _RESOLVED)
        identity = await resolve_user(request, await get_user(request))
        setattr(request.state, _RESOLVED, identity)
        return identity

    return _get_current_user
