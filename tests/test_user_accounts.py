"""register_users: callers resolved to their user account (forward-auth
provisioning and sync, local sessions, deactivation, audit), and the
store-backed login, reset, verification, profile, password and address
helpers in greentechhub_fastapi.users."""

import asyncio
import re

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.audit import InMemoryAuditStore
from greentechhub_core.email import InMemoryEmailSender
from greentechhub_core.identity import Identity
from greentechhub_core.security import InMemoryTokenStore, OneTimeTokens
from greentechhub_core.users import (
    InMemoryUserStore,
    ProvisioningPolicy,
    account_identity,
    set_password_sync,
)
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import (
    register_audit,
    register_auth,
    register_core,
    register_email,
    register_users,
)
from greentechhub_fastapi.auth import get_current_user, issue_token
from greentechhub_fastapi.auth.accounts import get_user_store, last_resolution
from greentechhub_fastapi.auth.cookies import SESSION_COOKIE_NAME
from greentechhub_fastapi.email import recipient_address
from greentechhub_fastapi.settings import Profile, ProfileError, SettingsViews
from greentechhub_fastapi.users import (
    AccountLoginViews,
    AccountPasswordResetViews,
    AccountVerificationViews,
    account_address,
    account_password_change,
    account_profile,
)

PROXY = ("10.0.0.1", 12345)
ALICE = {"X-authentik-username": "alice", "X-authentik-uid": "ak-1",
         "X-authentik-email": "alice@example.com", "X-authentik-name": "Alice"}


def _whoami(app: FastAPI) -> FastAPI:
    @app.get("/whoami")
    async def whoami(user: Identity | None = Depends(get_current_user)):
        if user is None:
            return None
        return {"subject": user.subject, "username": user.username, "email": user.email,
                "display_name": user.display_name, "provider": user.provider}

    return app


def _forward_auth_app(settings, store, **kwargs):
    settings.AUTH_ADAPTER = "forward_auth"
    settings.TRUSTED_PROXIES = "10.0.0.1"
    app = _whoami(FastAPI())
    register_core(app, settings)
    register_auth(app, settings)
    register_users(app, store, **kwargs)
    audit = InMemoryAuditStore()
    register_audit(app, settings, store=audit)
    return app, audit


def _local_app(settings, store):
    app = _whoami(FastAPI())
    register_auth(app, settings)
    register_users(app, store)
    return app


def _get(app, path, *, headers=None, cookies=None, client=PROXY):
    async def go():
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     cookies=cookies) as http:
            return await http.get(path, headers=headers)

    return asyncio.run(go())


# ── resolving callers ──────────────────────────────────────────────────────


def test_first_forward_auth_request_provisions_an_account(settings):
    store = InMemoryUserStore()
    app, audit = _forward_auth_app(settings, store, idp_label="Authentik")
    me = _get(app, "/whoami", headers=ALICE).json()
    [account] = store.list_users_sync()
    assert me == {"subject": account.id, "username": "alice", "email": "alice@example.com",
                  "display_name": "Alice", "provider": "authentik"}
    assert account.email_verified and account.auth_source == "authentik"
    assert [e.action for e in audit.entries_sync()] == ["user.provisioned"]
    assert get_user_store(app) is store


def test_later_requests_sync_idp_owned_fields(settings):
    store = InMemoryUserStore()
    app, audit = _forward_auth_app(settings, store)
    first = _get(app, "/whoami", headers=ALICE).json()
    again = _get(app, "/whoami", headers=ALICE).json()
    renamed = _get(app, "/whoami", headers={**ALICE, "X-authentik-name": "Alice Two"}).json()
    assert first["subject"] == again["subject"] == renamed["subject"]
    assert renamed["display_name"] == "Alice Two"
    assert [e.action for e in audit.entries_sync()] == ["user.synced", "user.provisioned"]


def test_an_unlinked_sign_in_without_provisioning_is_anonymous(settings):
    store = InMemoryUserStore()
    app, _ = _forward_auth_app(settings, store, policy=ProvisioningPolicy(auto_provision=False))
    assert _get(app, "/whoami", headers=ALICE).json() is None
    assert store.list_users_sync() == []


def test_untrusted_connections_still_resolve_nobody(settings):
    store = InMemoryUserStore()
    app, _ = _forward_auth_app(settings, store)
    assert _get(app, "/whoami", headers=ALICE, client=("203.0.113.9", 1)).json() is None
    assert store.list_users_sync() == []


def test_a_local_session_reads_the_account_and_deactivation_signs_out(settings):
    store = InMemoryUserStore()
    account = store.create_sync("alice", display_name="Alice")
    app = _local_app(settings, store)
    stale = Identity(subject=account.id, username="alice", email="old@example.com", groups=[],
                     claims={}, display_name="Old name")
    cookies = {SESSION_COOKIE_NAME: issue_token(app, stale)}
    store.update_sync(account.id, {"email": "new@example.com"})
    me = _get(app, "/whoami", cookies=cookies).json()
    assert (me["email"], me["display_name"]) == ("new@example.com", "Alice")
    store.update_sync(account.id, {"active": False})
    assert _get(app, "/whoami", cookies=cookies).json() is None


def test_a_session_for_no_account_is_anonymous(settings):
    app = _local_app(settings, InMemoryUserStore())
    ghost = Identity(subject="0" * 32, username="ghost", email=None, groups=[], claims={})
    assert _get(app, "/whoami", cookies={SESSION_COOKIE_NAME: issue_token(app, ghost)}).json() \
        is None


def test_resolution_is_cached_per_request(settings):
    class Counting(InMemoryUserStore):
        lookups = 0

        def find_link_sync(self, provider, external_subject):
            Counting.lookups += 1
            return super().find_link_sync(provider, external_subject)

    app, _ = _forward_auth_app(settings, Counting())

    async def user_twice(request: Request):
        resolve = request.app.dependency_overrides[get_current_user]
        first, second = await resolve(request), await resolve(request)
        return first is second, last_resolution(request).outcome

    @app.get("/twice")
    async def twice(result=Depends(user_twice)):
        return {"same": result[0], "outcome": result[1]}

    assert _get(app, "/twice", headers=ALICE).json() == {"same": True, "outcome": "provisioned"}
    assert Counting.lookups == 1


def test_without_register_users_the_adapter_identity_passes_through(settings):
    app = _whoami(FastAPI())
    register_auth(app, settings)
    identity = Identity(subject="alice", username="alice", email=None, groups=[], claims={})
    me = _get(app, "/whoami", cookies={SESSION_COOKIE_NAME: issue_token(app, identity)}).json()
    assert me["subject"] == "alice"


# ── store-backed views and hooks ───────────────────────────────────────────

TEMPLATES = Jinja2Templates(env=Environment(loader=DictLoader({
    "login_page.html": "LOGIN{% if error %} ERROR {{ error }}{% endif %}",
})))


def _login_app(store, **kwargs):
    from greentechhub_core.identity import DevelopmentIdentityProvider

    app = FastAPI()
    views = AccountLoginViews(templates=TEMPLATES, users=store,
                              identity_provider=DevelopmentIdentityProvider(secret_key="k" * 32),
                              **kwargs)
    app.include_router(views.router())
    return app


def _post(app, path, data):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.post(path, data=data)

    return asyncio.run(go())


def test_account_login_signs_in_with_the_account_subject():
    store = InMemoryUserStore()
    account = set_password_sync(store, store.create_sync("alice").id, "hunter2!")
    app = _login_app(store)
    response = _post(app, "/login", {"user_id": "Alice", "password": "hunter2!"})
    assert response.status_code == 303 and SESSION_COOKIE_NAME in response.cookies
    assert store.get_sync(account.id).last_login_at is not None
    assert _post(app, "/login", {"user_id": "alice", "password": "nope"}).status_code == 401


def test_account_login_can_require_a_confirmed_email():
    store = InMemoryUserStore()
    account = store.create_sync("alice", email="a@example.com")
    set_password_sync(store, account.id, "hunter2!")
    app = _login_app(store, require_verified=True)
    refused = _post(app, "/login", {"user_id": "alice", "password": "hunter2!"})
    assert refused.status_code == 403 and "Confirm your email" in refused.text
    store.update_sync(account.id, {"email_verified": True})
    assert _post(app, "/login", {"user_id": "alice", "password": "hunter2!"}).status_code == 303


def test_reset_finds_active_accounts_with_an_address():
    store = InMemoryUserStore()
    alice = store.create_sync("alice", email="a@example.com")
    store.create_sync("bob")
    carol = store.create_sync("carol", email="c@example.com")
    store.update_sync(carol.id, {"active": False})
    views = AccountPasswordResetViews(templates=TEMPLATES, users=store,
                                      tokens=OneTimeTokens(InMemoryTokenStore()))
    assert asyncio.run(views.find_account("alice")) == (alice.id, "a@example.com")
    assert asyncio.run(views.find_account("A@example.com")) == (alice.id, "a@example.com")
    assert asyncio.run(views.find_account("bob")) is None
    assert asyncio.run(views.find_account("carol")) is None
    asyncio.run(views.set_password(alice.id, "new-password"))
    assert store.get_sync(alice.id).password_hash


def test_verification_marks_the_current_address():
    store = InMemoryUserStore()
    alice = store.create_sync("alice", email="a@example.com")
    views = AccountVerificationViews(templates=TEMPLATES, users=store,
                                     tokens=OneTimeTokens(InMemoryTokenStore()))
    assert asyncio.run(views.find_unverified("alice")) == (alice.id, "a@example.com")
    asyncio.run(views.mark_verified(alice.id))
    assert store.get_sync(alice.id).email_verified
    assert asyncio.run(views.find_unverified("alice")) is None


def test_profile_hooks_edit_locally_and_lock_idp_fields():
    store = InMemoryUserStore()
    alice = store.create_sync("alice", email="a@example.com", email_verified=True)
    load, save = account_profile(store, idp_label="Authentik")
    local = account_identity(alice)
    assert asyncio.run(load(local)) == Profile(email="a@example.com", email_verified=True)
    asyncio.run(save(local, Profile(display_name="Alice", email="b@example.com")))
    updated = store.get_sync(alice.id)
    assert (updated.display_name, updated.email, updated.email_verified) == (
        "Alice", "b@example.com", False)

    via_idp = account_identity(updated, Identity(subject="ak-1", username="alice", email=None,
                                                 groups=[], claims={}, provider="authentik"))
    profile = asyncio.run(load(via_idp))
    assert profile.locked == frozenset({"display_name", "email"})
    assert profile.managed_by == "Authentik"


def test_profile_save_reports_a_taken_email():
    store = InMemoryUserStore()
    store.create_sync("bob", email="b@example.com")
    alice = store.create_sync("alice")
    _, save = account_profile(store)
    with pytest.raises(ProfileError) as refused:
        asyncio.run(save(account_identity(alice), Profile(email="B@example.com")))
    assert list(refused.value.errors) == ["email"]


def test_locked_fields_render_read_only_and_keep_their_value():
    views = SettingsViews(templates=TEMPLATES, load_profile=None, save_profile=None)
    section = views._profile_section(Profile(display_name="Alice", email="a@example.com",
                                             email_verified=False, locked=frozenset({"email"}),
                                             managed_by="Authentik"))
    name, email = section["settings"]
    assert "readonly" not in name
    assert email["readonly"] is True and email["help_text"] == "Managed by Authentik."
    assert email["input_type"] == "email"


def test_password_change_checks_the_current_password():
    store = InMemoryUserStore()
    alice = set_password_sync(store, store.create_sync("alice").id, "hunter2!")
    idp_only = store.create_sync("bob")
    change = account_password_change(store)
    assert asyncio.run(change(account_identity(alice), "wrong", "new-password")) is False
    assert asyncio.run(change(account_identity(alice), "hunter2!", "new-password")) is True
    assert asyncio.run(change(account_identity(idp_only), "", "new-password")) is False


def test_address_for_only_returns_confirmed_active_addresses():
    store = InMemoryUserStore()
    alice = store.create_sync("alice", email="a@example.com")
    address_for = account_address(store)
    assert asyncio.run(address_for(alice.id)) is None
    assert asyncio.run(account_address(store, verified_only=False)(alice.id)) == "a@example.com"
    store.update_sync(alice.id, {"email_verified": True})
    assert asyncio.run(address_for(alice.id)) == "a@example.com"
    store.update_sync(alice.id, {"active": False})
    assert asyncio.run(address_for(alice.id)) is None
    assert asyncio.run(address_for("0" * 32)) is None


def test_recipient_address_falls_back_to_the_identity_without_address_for():
    app = FastAPI()
    register_email(app, None, sender=InMemoryEmailSender())
    identity = Identity(subject="x", username="x", email="x@example.com", groups=[], claims={})
    assert asyncio.run(recipient_address(app, identity)) == "x@example.com"
    assert asyncio.run(recipient_address(app, "x")) is None


def test_emailed_links_still_reach_unconfirmed_addresses():
    """Verification sends to the address it's given, never via address_for."""
    store = InMemoryUserStore()
    alice = store.create_sync("alice", email="a@example.com")
    app = FastAPI()
    sender = InMemoryEmailSender()
    register_email(app, None, sender=sender, address_for=account_address(store),
                   base_url="https://app.example")
    views = AccountVerificationViews(templates=TEMPLATES, users=store,
                                     tokens=OneTimeTokens(InMemoryTokenStore()))
    asyncio.run(views.send_link(app, alice.id, "a@example.com"))
    [message] = sender.outbox
    assert re.search(r"https://app\.example/verify-email/\S+", message.text)
