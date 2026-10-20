"""register_scim: the inbound SCIM 2.0 Users endpoint — bearer auth, create
with an externalId link, filters and paging, PUT/PATCH sync, deactivation,
clashes and errors, and a pushed account meeting its forward-auth sign-in."""

import asyncio

import httpx
import pytest
from fastapi import Depends, FastAPI
from greentechhub_core.audit import InMemoryAuditStore
from greentechhub_core.users import InMemoryUserStore

from greentechhub_fastapi import (
    register_audit,
    register_auth,
    register_core,
    register_scim,
    register_users,
)
from greentechhub_fastapi.auth import get_current_user
from greentechhub_fastapi.scim import PATCH_SCHEMA, USER_SCHEMA

TOKEN = "scim-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ALICE = {"schemas": [USER_SCHEMA], "userName": "alice", "externalId": "ak-1",
         "displayName": "Alice", "emails": [{"value": "Alice@example.com", "primary": True}],
         "active": True}


@pytest.fixture
def setup(settings):
    settings.AUTH_ADAPTER = "forward_auth"
    settings.TRUSTED_PROXIES = "10.0.0.1"
    app = FastAPI()
    register_core(app, settings)
    register_auth(app, settings)
    store = InMemoryUserStore()
    register_users(app, store)
    audit = InMemoryAuditStore()
    register_audit(app, settings, store=audit)
    register_scim(app, token=TOKEN)

    @app.get("/whoami")
    async def whoami(user=Depends(get_current_user)):
        return user.subject if user else None

    return app, store, audit


def _call(app, method, path, *, json=None, headers=AUTH, client=("10.0.0.1", 1)):
    async def go():
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.request(method, path, json=json, headers=headers)

    return asyncio.run(go())


def _patch(*operations):
    return {"schemas": [PATCH_SCHEMA], "Operations": list(operations)}


def test_every_route_needs_the_token(setup):
    app, _, _ = setup
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}):
        response = _call(app, "GET", "/scim/v2/Users", headers=headers)
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/scim+json")


def test_an_empty_token_is_refused():
    with pytest.raises(ValueError):
        register_scim(FastAPI(), token="")


def test_discovery_endpoints(setup):
    app, _, _ = setup
    assert _call(app, "GET", "/scim/v2/ServiceProviderConfig").json()["patch"] == {
        "supported": True}
    assert _call(app, "GET", "/scim/v2/ResourceTypes").json()["Resources"][0]["id"] == "User"
    assert _call(app, "GET", "/scim/v2/Schemas").json()["Resources"][0]["id"] == USER_SCHEMA


def test_create_links_the_external_id(setup):
    app, store, audit = setup
    response = _call(app, "POST", "/scim/v2/Users", json=ALICE)
    assert response.status_code == 201
    body = response.json()
    assert (body["userName"], body["externalId"], body["displayName"], body["active"]) == (
        "alice", "ak-1", "Alice", True)
    assert body["emails"][0]["value"] == "alice@example.com"
    assert response.headers["Location"].endswith(f"/scim/v2/Users/{body['id']}")
    account = store.get_sync(body["id"])
    assert account.email_verified and account.auth_source == "authentik"
    assert store.find_link_sync("authentik", "ak-1").user_id == account.id
    assert [e.action for e in audit.entries_sync()] == ["user.provisioned"]


def test_a_pushed_account_meets_its_forward_auth_sign_in(setup):
    app, store, _ = setup
    pushed = _call(app, "POST", "/scim/v2/Users", json=ALICE).json()
    subject = _call(app, "GET", "/whoami", headers={"X-authentik-username": "alice",
                                                    "X-authentik-uid": "ak-1"}).json()
    assert subject == pushed["id"] and len(store.list_users_sync()) == 1


def test_create_clashes_are_409_uniqueness(setup):
    app, _, _ = setup
    _call(app, "POST", "/scim/v2/Users", json=ALICE)
    for body in (ALICE, {**ALICE, "externalId": "ak-2"},
                 {**ALICE, "userName": "bob", "emails": []}):
        response = _call(app, "POST", "/scim/v2/Users", json=body)
        assert response.status_code == 409 and response.json()["scimType"] == "uniqueness"


def test_create_needs_a_username_and_json(setup):
    app, _, _ = setup
    assert _call(app, "POST", "/scim/v2/Users", json={"externalId": "x"}).status_code == 400
    assert _call(app, "POST", "/scim/v2/Users", json=["nope"]).status_code == 400
    bad = _call(app, "POST", "/scim/v2/Users", json={"userName": "two words"})
    assert bad.status_code == 400 and bad.json()["scimType"] == "invalidValue"


def test_get_list_filter_and_page(setup):
    app, _, _ = setup
    alice = _call(app, "POST", "/scim/v2/Users", json=ALICE).json()
    _call(app, "POST", "/scim/v2/Users", json={"userName": "bob"})
    assert _call(app, "GET", f"/scim/v2/Users/{alice['id']}").json()["userName"] == "alice"
    assert _call(app, "GET", "/scim/v2/Users/" + "0" * 32).status_code == 404
    listed = _call(app, "GET", "/scim/v2/Users?startIndex=2&count=1").json()
    assert (listed["totalResults"], listed["itemsPerPage"]) == (2, 1)
    assert listed["Resources"][0]["userName"] == "bob"
    by_name = _call(app, "GET", '/scim/v2/Users?filter=userName eq "ALICE"').json()
    assert [r["id"] for r in by_name["Resources"]] == [alice["id"]]
    by_external = _call(app, "GET", '/scim/v2/Users?filter=externalId eq "ak-1"').json()
    assert [r["id"] for r in by_external["Resources"]] == [alice["id"]]
    none = _call(app, "GET", '/scim/v2/Users?filter=userName eq "nobody"').json()
    assert none["totalResults"] == 0 and none["Resources"] == []
    bad = _call(app, "GET", '/scim/v2/Users?filter=emails co "x"')
    assert bad.status_code == 400 and bad.json()["scimType"] == "invalidFilter"


def test_put_replaces(setup):
    app, store, _ = setup
    alice = _call(app, "POST", "/scim/v2/Users", json=ALICE).json()
    replaced = _call(app, "PUT", f"/scim/v2/Users/{alice['id']}",
                     json={"userName": "alice2", "externalId": "ak-1"}).json()
    assert replaced["userName"] == "alice2"
    assert "displayName" not in replaced and "emails" not in replaced
    assert store.get_sync(alice["id"]).email is None


def test_patch_with_paths_and_path_less_values(setup):
    app, store, audit = setup
    alice = _call(app, "POST", "/scim/v2/Users", json=ALICE).json()
    url = f"/scim/v2/Users/{alice['id']}"
    patched = _call(app, "PATCH", url, json=_patch(
        {"op": "Replace", "path": "displayName", "value": "Alice Two"},
        {"op": "replace", "path": 'emails[type eq "work"].value', "value": "new@example.com"},
    )).json()
    assert patched["displayName"] == "Alice Two"
    assert patched["emails"][0]["value"] == "new@example.com"
    assert store.get_sync(alice["id"]).email_verified
    patched = _call(app, "PATCH", url, json=_patch(
        {"op": "replace", "value": {"name": {"givenName": "Al", "familyName": "Smith"}}})).json()
    assert patched["displayName"] == "Al Smith"
    deactivated = _call(app, "PATCH", url, json=_patch(
        {"op": "replace", "path": "active", "value": "False"})).json()
    assert deactivated["active"] is False
    assert audit.entries_sync()[0].action == "user.deactivated"


def test_patch_errors(setup):
    app, _, _ = setup
    alice = _call(app, "POST", "/scim/v2/Users", json=ALICE).json()
    url = f"/scim/v2/Users/{alice['id']}"
    for operations, scim_type in (
        ([{"op": "move", "path": "active", "value": True}], "invalidSyntax"),
        ([{"op": "replace", "path": "title", "value": "x"}], "invalidPath"),
        ([{"op": "replace", "value": "not an object"}], "invalidSyntax"),
        ([{"op": "replace", "path": "active", "value": "maybe"}], "invalidValue"),
    ):
        response = _call(app, "PATCH", url, json=_patch(*operations))
        assert response.status_code == 400 and response.json()["scimType"] == scim_type
    assert _call(app, "PATCH", url, json={"Operations": "x"}).status_code == 400


def test_patch_can_move_the_external_id(setup):
    app, store, _ = setup
    alice = _call(app, "POST", "/scim/v2/Users", json=ALICE).json()
    bob = _call(app, "POST", "/scim/v2/Users", json={"userName": "bob", "externalId": "ak-2"})
    url = f"/scim/v2/Users/{alice['id']}"
    _call(app, "PATCH", url, json=_patch({"op": "replace", "path": "externalId", "value": "ak-9"}))
    assert store.find_link_sync("authentik", "ak-1") is None
    assert store.find_link_sync("authentik", "ak-9").user_id == alice["id"]
    taken = _call(app, "PATCH", url, json=_patch(
        {"op": "replace", "path": "externalId", "value": "ak-2"}))
    assert taken.status_code == 409
    assert store.find_link_sync("authentik", "ak-2").user_id == bob.json()["id"]


def test_delete_deactivates_and_signs_out(setup):
    app, store, _ = setup
    alice = _call(app, "POST", "/scim/v2/Users", json=ALICE).json()
    headers = {"X-authentik-username": "alice", "X-authentik-uid": "ak-1"}
    assert _call(app, "GET", "/whoami", headers=headers).json() == alice["id"]
    assert _call(app, "DELETE", f"/scim/v2/Users/{alice['id']}").status_code == 204
    assert store.get_sync(alice["id"]).active is False
    assert _call(app, "GET", "/whoami", headers=headers).json() is None


def test_groups_are_not_implemented(setup):
    app, _, _ = setup
    assert _call(app, "POST", "/scim/v2/Groups", json={}).status_code == 501
    assert _call(app, "GET", "/scim/v2/Groups/x").status_code == 501
