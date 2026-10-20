"""register_users — install greentechhub-core's UserStore, so register_auth
resolves every caller to their user account (see auth/accounts.py).

Call it before the first request; the order relative to register_auth
doesn't matter (the wrapper register_auth installs reads app.state per
request).
"""

from fastapi import FastAPI
from greentechhub_core.users import ProvisioningPolicy, UserStore

from greentechhub_fastapi.auth.accounts import USERS_STATE_KEY, UsersConfig


def register_users(
    app: FastAPI,
    store: UserStore,
    *,
    policy: ProvisioningPolicy | None = None,
    idp_label: str = "your identity provider",
) -> None:
    """Resolve callers through `store`.

    Args:
        store: the UserStore (core's SQLAlchemyUserStore over gth_users and
            gth_user_identities).
        policy: core's ProvisioningPolicy for IdP sign-ins — by default
            provision on first sign-in, never link by email, and keep email
            and display name in step with the IdP.
        idp_label: the IdP's name on pages ("Managed by Authentik").
    """
    setattr(app.state, USERS_STATE_KEY,
            UsersConfig(store=store, policy=policy or ProvisioningPolicy(), idp_label=idp_label))
