"""users — ready-made sign-in, password reset, email verification and profile
over greentechhub-core's UserStore, so a service on register_users writes
none of the account lookups those views otherwise leave abstract.

    store = SQLAlchemyUserStore(USERS, USER_IDENTITIES, async_session_factory=Session)
    register_users(app, store, idp_label="Authentik")
    register_auth(app, settings)
    register_email(app, settings, sender=..., address_for=account_address(store), base_url=...)

    login = AccountLoginViews(templates=t, identity_provider=provider, users=store)
    reset = AccountPasswordResetViews(templates=t, tokens=tokens, users=store)
    verify = AccountVerificationViews(templates=t, tokens=tokens, users=store)
    load_profile, save_profile = account_profile(store)
    SettingsViews(templates=t, load_profile=load_profile, save_profile=save_profile,
                  verification=verify, change_password=account_password_change(store))

Every lookup takes the Identity's subject as the account id: register_auth
resolves callers to their account (auth.accounts) once register_users ran.
"""

from collections.abc import Awaitable, Callable

from greentechhub_core.identity import Identity
from greentechhub_core.security import verify_password
from greentechhub_core.users import (
    LOCAL_PROVIDER,
    ProvisioningPolicy,
    UserAccount,
    UserExists,
    UserStore,
    account_identity,
    authenticate,
    set_password,
)

from greentechhub_fastapi.auth.reset import PasswordResetViews
from greentechhub_fastapi.auth.verify import EmailVerificationViews
from greentechhub_fastapi.auth.views import LoginViews
from greentechhub_fastapi.settings import Profile, ProfileError

EMAIL_TAKEN = "That email address is already used by another account."
_PROFILE_FIELDS = frozenset({"display_name", "email"})


async def _account_for(store: UserStore, identifier: str) -> UserAccount | None:
    """The account a user ID or email names (the forms accept either)."""
    if "@" in identifier:
        return await store.by_email(identifier) or await store.by_username(identifier)
    return await store.by_username(identifier)


class AccountLoginViews(LoginViews):
    """LoginViews whose credential check is core's `authenticate` over `users`.

    `require_verified=True` turns away a correct password while the
    account's email address is unconfirmed (an account without one signs
    in), with `unverified_message`; pair it with AccountVerificationViews
    and set `verify_resend_url`.
    """

    unverified_message: str = "Confirm your email address first: we've sent you a link."

    def __init__(self, *, users: UserStore, require_verified: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._users = users
        self._require_verified = require_verified

    async def authenticate(self, user_id: str, password: str) -> Identity | None:
        account = await authenticate(self._users, user_id, password)
        return account_identity(account) if account is not None else None

    async def refuse_sign_in(self, identity: Identity) -> str | None:
        if self._require_verified and identity.email and not identity.email_verified:
            return self.unverified_message
        return None


class AccountPasswordResetViews(PasswordResetViews):
    """PasswordResetViews over `users`: the forgot form takes a user ID or an
    email, and only an active account with an address gets a link."""

    def __init__(self, *, users: UserStore, **kwargs) -> None:
        super().__init__(**kwargs)
        self._users = users

    async def find_account(self, identifier: str) -> tuple[str, str] | None:
        account = await _account_for(self._users, identifier)
        if account is None or not account.active or not account.email:
            return None
        return account.id, account.email

    async def set_password(self, subject: str, password: str) -> None:
        await set_password(self._users, subject, password)


class AccountVerificationViews(EmailVerificationViews):
    """EmailVerificationViews over `users`: a used link marks the account's
    current address confirmed."""

    def __init__(self, *, users: UserStore, **kwargs) -> None:
        super().__init__(**kwargs)
        self._users = users

    async def mark_verified(self, subject: str) -> None:
        await self._users.update(subject, {"email_verified": True})

    async def find_unverified(self, identifier: str) -> tuple[str, str] | None:
        account = await _account_for(self._users, identifier)
        if account is None or not account.active or not account.email or account.email_verified:
            return None
        return account.id, account.email


def account_profile(
    store: UserStore,
    *,
    policy: ProvisioningPolicy | None = None,
    idp_label: str = "your identity provider",
) -> tuple[Callable[[Identity], Awaitable[Profile]],
           Callable[[Identity, Profile], Awaitable[None]]]:
    """SettingsViews' (load_profile, save_profile) over `store`.

    Someone signed in through an IdP (Identity.provider other than "local")
    sees the fields `policy.idp_owned` names locked, "Managed by
    {idp_label}": the IdP's value would overwrite an edit on their next
    request anyway. A changed email is saved unconfirmed (core's
    apply_changes); a taken one is a ProfileError on the email field.
    """
    owned = (policy or ProvisioningPolicy()).idp_owned & _PROFILE_FIELDS

    async def load_profile(user: Identity) -> Profile:
        account = await store.get(user.subject)
        if account is None:
            return Profile()
        locked = owned if user.provider != LOCAL_PROVIDER else frozenset()
        return Profile(display_name=account.display_name or "", email=account.email or "",
                       email_verified=account.email_verified, locked=locked,
                       managed_by=idp_label if locked else "")

    async def save_profile(user: Identity, profile: Profile) -> None:
        changes = {key: getattr(profile, key) or None
                   for key in _PROFILE_FIELDS - profile.locked}
        try:
            await store.update(user.subject, changes)
        except UserExists as clash:
            raise ProfileError({clash.field: [EMAIL_TAKEN]}) from clash

    return load_profile, save_profile


def account_password_change(store: UserStore) -> Callable[[Identity, str, str], Awaitable[bool]]:
    """SettingsViews' `change_password` over `store`: False unless `current`
    is the account's password (an IdP-only account has none, so it can't
    set one this way)."""

    async def change_password(user: Identity, current: str, new: str) -> bool:
        account = await store.get(user.subject)
        if account is None or account.password_hash is None:
            return False
        if not verify_password(current, account.password_hash):
            return False
        await set_password(store, account.id, new)
        return True

    return change_password


def account_address(
    store: UserStore, *, verified_only: bool = True
) -> Callable[[str], Awaitable[str | None]]:
    """register_email's `address_for` over `store`: an active account's email,
    and by default only once it's confirmed, so notices never go to an
    address nobody has proved they own."""

    async def address_for(subject: str) -> str | None:
        account = await store.get(subject)
        if account is None or not account.active or not account.email:
            return None
        if verified_only and not account.email_verified:
            return None
        return account.email

    return address_for
