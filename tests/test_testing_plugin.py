"""testing: the HTTP fixtures, run in an inner pytest session the way a
service's conftest loads them, against a small app with register_auth and a
CSRF-protected LoginViews: web_login/client_as sign in through the form
(CSRF and the Secure cookies included), the app's dependency_overrides
survive every test, gth_db routes a Database to the test transaction, and
the helpers parse HX-Trigger."""

import pytest

pytest_plugins = ["pytester"]

APP = '''
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.identity import Identity
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_auth
from greentechhub_fastapi.auth import get_current_user
from greentechhub_fastapi.auth.tokens import IDENTITY_PROVIDER_STATE_KEY
from greentechhub_fastapi.auth.views import LoginViews

USERS = {}


class Settings(GTHBaseSettings):
    pass


class Views(LoginViews):
    csrf = True

    async def authenticate(self, user_id, password):
        if USERS.get(user_id) == password:
            return Identity(subject=user_id, username=user_id, email=None, groups=[], claims={})
        return None


app = FastAPI()
register_auth(app, Settings(secret_key="test-secret"))
templates = Jinja2Templates(env=Environment(loader=DictLoader({
    "login_page.html": "Sign in{% if error %}: {{ error }}{% endif %}"})))
provider = getattr(app.state, IDENTITY_PROVIDER_STATE_KEY)
app.include_router(Views(templates=templates, identity_provider=provider).router())


@app.get("/me")
async def me(user=Depends(get_current_user)):
    return {"subject": user.subject if user else None}


@app.get("/toast")
async def toast():
    return JSONResponse({}, headers={"HX-Trigger": '{"showToast": {"message": "Saved"}}'})
'''

CONFTEST = '''
import pytest

pytest_plugins = ["greentechhub_fastapi.testing"]

from app import USERS, app


@pytest.fixture
def gth_app():
    return app


@pytest.fixture
def gth_create_user():
    async def create(user_id, password):
        USERS[user_id] = password
    return create
'''


def _run(pytester: pytest.Pytester, tests: str, conftest: str = CONFTEST) -> pytest.RunResult:
    pytester.makeini("[pytest]\nasyncio_mode = auto\n")
    pytester.makepyfile(app=APP)
    pytester.makeconftest(conftest)
    pytester.makepyfile(test_inner=tests)
    return pytester.runpytest_subprocess("-p", "no:cacheprovider")


def test_signing_in_through_the_form(pytester: pytest.Pytester):
    result = _run(pytester, '''
import pytest
from app import USERS
from greentechhub_fastapi.testing import hx_triggers, post_login, web_login


async def test_hx_triggers(gth_client):
    assert hx_triggers(await gth_client.get("/toast")) == {"showToast": {"message": "Saved"}}


async def test_anonymous(gth_client):
    assert (await gth_client.get("/me")).json() == {"subject": None}


async def test_web_login_keeps_the_session(gth_client):
    USERS["bob"] = "pw"
    await web_login(gth_client, "bob", "pw")
    assert (await gth_client.get("/me")).json() == {"subject": "bob"}


async def test_post_login_sends_the_csrf_token(gth_client):
    USERS["carol"] = "pw"
    ok = await post_login(gth_client, "carol", "pw", follow_redirects=False)
    assert ok.status_code == 303
    gth_client.cookies.clear()
    refused = await gth_client.post("/login", data={"user_id": "carol", "password": "pw"})
    assert refused.status_code == 403


async def test_web_login_fails_loudly(gth_client):
    with pytest.raises(AssertionError, match="sign-in as 'nobody' failed"):
        await web_login(gth_client, "nobody", "wrong")


async def test_client_as_gives_each_persona_a_client(client_as):
    alice, dave = await client_as("alice"), await client_as("dave", password="other")
    assert (await alice.get("/me")).json() == {"subject": "alice"}
    assert (await dave.get("/me")).json() == {"subject": "dave"}
''')
    result.assert_outcomes(passed=6)


def test_dependency_overrides_are_restored_not_cleared(pytester: pytest.Pytester):
    result = _run(pytester, '''
from app import app
from greentechhub_fastapi.auth import get_current_user


def _marker():
    return None


async def test_a_adds_an_override(gth_client):
    app.dependency_overrides[_marker] = _marker
    app.dependency_overrides.clear()  # what a test might do


async def test_b_auth_is_still_registered(gth_client):
    assert get_current_user in app.dependency_overrides
    assert _marker not in app.dependency_overrides
''')
    result.assert_outcomes(passed=2)


def test_gth_db_routes_the_database_to_the_test_transaction(pytester: pytest.Pytester):
    conftest = CONFTEST + '''
from greentechhub_core.sqlalchemy import Database

DB = Database("")  # no URL: anything that reaches a real engine fails


@pytest.fixture
def gth_db():
    return DB
'''
    result = _run(pytester, '''
from sqlalchemy import text
from conftest import DB


async def test_sessions_use_the_test_connection(gth_client, gth_connection):
    async for session in DB.session():
        assert session.bind is gth_connection
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    assert (await DB.ready()).status == "healthy"
''', conftest=conftest)
    result.assert_outcomes(passed=1)


def test_a_missing_gth_app_says_to_override_it(pytester: pytest.Pytester):
    result = _run(pytester, '''
async def test_needs_the_app(gth_client):
    pass
''', conftest='pytest_plugins = ["greentechhub_fastapi.testing"]\n')
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*override the gth_app fixture*"])
