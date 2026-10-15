"""Personal API tokens: register_api_tokens + register_auth(bearer=True) sign a
token's owner in, capped to the token's scopes; SettingsViews(api_tokens=)
adds the "API tokens" section that creates (shown once), lists and revokes
them, and a token can't manage tokens itself."""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from html import unescape

import httpx
import pytest
from fastapi import APIRouter, Depends
from fastapi.templating import Jinja2Templates
from greentechhub_core.audit import InMemoryAuditStore
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.permissions import InMemoryGrantStore, Permission, Role
from greentechhub_core.security import InMemoryApiTokenStore
from greentechhub_core.settings import InMemorySettingsStore, SettingsRegistry

from greentechhub_fastapi import (
    register_api_tokens,
    register_audit,
    register_auth,
    register_csrf,
    register_permissions,
    register_settings,
)
from greentechhub_fastapi.api_tokens import ApiTokenViews
from greentechhub_fastapi.auth import issue_token
from greentechhub_fastapi.auth.dependency import get_current_user
from greentechhub_fastapi.dependencies import get_current_identity
from greentechhub_fastapi.permissions import require_permission
from greentechhub_fastapi.settings import SettingsViews
from greentechhub_fastapi.testing import hx_triggers
from tests.conftest import build_app
from tests.test_role_admin import _Settings

READ, WRITE, ADMIN = Permission("stock.read"), Permission("stock.write"), Permission("users.manage")
ROLES = (Role(name="trader", permissions={READ, WRITE}), Role(name="admin", permissions={ADMIN}))
HTML = {"Accept": "text/html"}

# Stand-ins for greentechhub-ui's settings_page.html / api_tokens_section.html:
# they print the data.
SECTION = """SECTION {{ section.id }} template={{ section.template }} action={{ section.action }}
CHOICES {{ section.scope_choices|join(',') }} EXPIRY {{ section.expiry_choices|join(',') }}
{% for t in section.tokens %}TOKEN {{ t.id }} {{ t.name }} scopes={{ t.scopes|join(',') }} \
used={{ 'yes' if t.last_used_at else 'no' }} expired={{ t.expired }} revoke={{ t.revoke_url }}
{% endfor %}{% if section.created %}CREATED {{ section.created.name }} {{ section.created.token }}
{% endif %}{% for field, messages in (section.errors or {}).items() %}\
ERR {{ field }}={{ messages|join(' ') }}
{% endfor %}"""
PAGE = """{% for section in settings_sections %}{% if section.id == 'api_tokens' %}\
{% include section.template %}{% else %}OTHER {{ section.id }}
{% endif %}{% endfor %}"""


@pytest.fixture
def token_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ROLE_BOOTSTRAP", "root=admin")
    return _Settings()


@pytest.fixture
def templates(tmp_path):
    (tmp_path / "settings_page.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "api_tokens_section.html").write_text(SECTION, encoding="utf-8")
    return Jinja2Templates(directory=tmp_path)


class _Env:
    def __init__(self, settings, templates, *, csrf=False, audit=False, store=True):
        self.grants = InMemoryGrantStore()
        self.grants.assign_sync("alice", "trader")
        self.grants.assign_sync("bob", "trader")
        self.now: datetime | None = None  # None: the real time
        self.tokens = InMemoryApiTokenStore(clock=lambda: self.now or datetime.now(UTC))
        self.audit = InMemoryAuditStore()
        app = build_app(settings)
        register_auth(app, settings, bearer=True)
        register_permissions(app, settings, roles=ROLES, grants=self.grants)
        if store:
            register_api_tokens(app, settings, store=self.tokens)
        if audit:
            register_audit(app, settings, store=self.audit)
        if csrf:
            register_csrf(app)
        register_settings(app, settings, registry=SettingsRegistry([]),
                          store=InMemorySettingsStore(),
                          views=SettingsViews(templates=templates, csrf=csrf,
                                              api_tokens=ApiTokenViews(templates=templates)))
        api = APIRouter(prefix="/api")

        @api.get("/stocks")
        async def stocks(user: Identity = Depends(require_permission("stock.read"))):
            return {"as": user.subject}

        @api.post("/stocks")
        async def add_stock(user: Identity = Depends(require_permission("stock.write"))):
            return {"as": user.subject}

        @api.get("/me")
        async def me(user: Identity = Depends(get_current_identity)):
            return {"as": user.subject}

        @api.get("/who")
        async def who(user: Identity | None = Depends(get_current_user)):
            return {"as": user.subject if user else None}

        app.include_router(api)
        self.app = app

    def call(self, method, path, *, subject=None, bearer=None, data=None, headers=None):
        async def go():
            cookies = {}
            if subject:
                provider = DevelopmentIdentityProvider(secret_key="test-secret")
                cookies["gth_session"] = provider.issue(
                    Identity(subject=subject, username=subject, email=None, groups=[], claims={}))
            all_headers = {**HTML, **(headers or {})}
            if bearer:
                all_headers["Authorization"] = f"Bearer {bearer}"
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                         cookies=cookies) as client:
                return await client.request(method, path, data=data, headers=all_headers)

        return asyncio.run(go())

    def create(self, subject="alice", name="backup", scopes=("stock.read",), expiry="90"):
        return self.call("POST", "/settings/api-tokens", subject=subject,
                         data={"name": name, "scopes": list(scopes), "expires_in_days": expiry})


def _created(response) -> str:
    return re.search(r"^CREATED \S+ (\S+)$", response.text, re.M).group(1)


def _token_ids(response) -> list[str]:
    return re.findall(r"^TOKEN (\S+)", response.text, re.M)


def test_a_script_authenticates_with_a_token_until_it_is_revoked(token_settings, templates):
    env = _Env(token_settings, templates)
    created = env.create()
    assert created.status_code == 200
    assert hx_triggers(created)["showToast"]["message"] == "Token created"
    plaintext = _created(created)
    assert env.call("GET", "/api/stocks", bearer=plaintext).json() == {"as": "alice"}

    [token_id] = _token_ids(created)
    revoked = env.call("DELETE", f"/settings/api-tokens/{token_id}", subject="alice")
    assert revoked.status_code == 200
    assert hx_triggers(revoked)["showToast"]["message"] == "Token revoked"
    assert _token_ids(revoked) == []
    assert env.call("GET", "/api/stocks", bearer=plaintext).status_code == 401


def test_a_token_holds_only_its_scopes(token_settings, templates):
    env = _Env(token_settings, templates)
    plaintext = _created(env.create(scopes=["stock.read"]))
    assert env.call("POST", "/api/stocks", subject="alice").status_code == 200  # alice can
    assert env.call("POST", "/api/stocks", bearer=plaintext).status_code == 403  # her token can't


def test_a_token_loses_a_permission_its_owner_loses(token_settings, templates):
    env = _Env(token_settings, templates)
    plaintext = _created(env.create(scopes=["stock.read", "stock.write"]))
    assert env.call("POST", "/api/stocks", bearer=plaintext).status_code == 200
    env.grants.revoke_sync("alice", "trader")
    assert env.call("GET", "/api/stocks", bearer=plaintext).status_code == 403
    assert env.call("GET", "/api/me", bearer=plaintext).json() == {"as": "alice"}


def test_scopes_are_capped_by_the_owners_permissions_at_creation(token_settings, templates):
    env = _Env(token_settings, templates)
    response = env.create(scopes=["stock.read", "users.manage"])
    assert response.status_code == 422
    assert "ERR scopes=You can't give a token users.manage." in unescape(response.text)
    assert env.tokens.list_for_sync("alice") == []


def test_the_section_lists_only_the_users_tokens_and_shows_a_plaintext_once(token_settings,
                                                                           templates):
    env = _Env(token_settings, templates)
    plaintext = _created(env.create(name="alices"))
    env.create(subject="bob", name="bobs")
    env.call("GET", "/api/stocks", bearer=plaintext)
    page = env.call("GET", "/settings", subject="alice").text
    assert "SECTION api_tokens template=api_tokens_section.html action=/settings/api-tokens" in page
    assert "CHOICES stock.read,stock.write EXPIRY 30,90,365,None" in page
    assert re.search(r"TOKEN \S+ alices scopes=stock.read used=yes expired=False", page)
    assert "bobs" not in page and plaintext not in page and "CREATED" not in page


@pytest.mark.parametrize("name,expiry,error", [
    ("", "90", "ERR name=Give the token a name."),
    ("x" * 81, "90", "ERR name=At most 80 characters."),
    ("ok", "7", "ERR expires_in_days=Choose one of the offered expiries."),
    ("ok", "soon", "ERR expires_in_days=Choose one of the offered expiries."),
])
def test_bad_fields_are_422(token_settings, templates, name, expiry, error):
    env = _Env(token_settings, templates)
    response = env.create(name=name, expiry=expiry)
    assert response.status_code == 422 and error in response.text


def test_a_blank_expiry_is_never_and_a_dated_one_expires(token_settings, templates):
    env = _Env(token_settings, templates)
    _created(env.create(name="forever", expiry=""))
    dated = _created(env.create(name="month", expiry="30"))
    by_name = {t.name: t for t in env.tokens.list_for_sync("alice")}
    assert by_name["forever"].expires_at is None
    assert by_name["month"].expires_at - datetime.now(UTC) > timedelta(days=29)

    env.now = datetime.now(UTC) + timedelta(days=31)
    assert env.call("GET", "/api/stocks", bearer=dated).status_code == 401


def test_revoking_someone_elses_token_is_404(token_settings, templates):
    env = _Env(token_settings, templates)
    plaintext = _created(env.create(subject="bob"))
    [bobs] = env.tokens.list_for_sync("bob")
    assert env.call("DELETE", f"/settings/api-tokens/{bobs.id}", subject="alice").status_code == 404
    assert env.call("GET", "/api/stocks", bearer=plaintext).status_code == 200


def test_a_token_cant_manage_tokens(token_settings, templates):
    env = _Env(token_settings, templates)
    plaintext = _created(env.create())
    [token] = env.tokens.list_for_sync("alice")
    data = {"name": "more", "scopes": ["stock.read"], "expires_in_days": "90"}
    assert env.call("POST", "/settings/api-tokens", bearer=plaintext, data=data).status_code == 403
    assert env.call("DELETE", f"/settings/api-tokens/{token.id}",
                    bearer=plaintext).status_code == 403
    assert len(env.tokens.list_for_sync("alice")) == 1


def test_jwt_bearer_and_cookie_still_work(token_settings, templates):
    env = _Env(token_settings, templates)
    identity = Identity(subject="alice", username="alice", email=None, groups=[], claims={})
    jwt = issue_token(env.app, identity)
    assert env.call("GET", "/api/stocks", bearer=jwt).json() == {"as": "alice"}
    assert env.call("POST", "/api/stocks", bearer=jwt).status_code == 200  # not capped
    assert env.call("GET", "/api/stocks", subject="alice").json() == {"as": "alice"}


def test_a_bad_personal_token_never_falls_back_to_the_cookie(token_settings, templates):
    env = _Env(token_settings, templates)
    assert env.call("GET", "/api/who", subject="alice", bearer="not-a-token").json() == {"as": None}


def test_without_register_api_tokens_a_personal_token_is_nobody(token_settings, templates):
    env = _Env(token_settings, templates, store=False)
    assert env.call("GET", "/api/who", bearer="abc123").json() == {"as": None}


def test_creating_and_revoking_are_audited_without_the_token(token_settings, templates):
    env = _Env(token_settings, templates, audit=True)
    plaintext = _created(env.create())
    [token] = env.tokens.list_for_sync("alice")
    env.call("DELETE", f"/settings/api-tokens/{token.id}", subject="alice")
    entries = env.audit.entries_sync()
    assert [e.action for e in entries] == ["api_token.revoked", "api_token.created"]
    assert all(e.actor == "alice" and (e.target_type, e.target_id) == ("api_token", token.id)
               for e in entries)
    assert all(plaintext not in repr(e) for e in entries)


def test_with_csrf_the_routes_need_the_token(token_settings, templates):
    env = _Env(token_settings, templates, csrf=True)
    assert env.create().status_code == 403
