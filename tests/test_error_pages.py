"""register_error_pages: greentechhub-ui's 403/404/500 pages for browser page
requests (HTML, not htmx, not under the API prefix), wrapping whatever handlers
were registered before so API and htmx requests keep the JSON defaults; the
500 page renders failure-proof with a minimal context."""

import asyncio

import httpx
import pytest
from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.types import NotFoundError
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import (
    register_api_error_handlers,
    register_csp,
    register_error_pages,
    register_permissions,
)
from greentechhub_fastapi.dependencies.identity import require_page_identity
from greentechhub_fastapi.exceptions import wants_error_page
from greentechhub_fastapi.permissions import require_page_permission
from tests.conftest import build_app

HTML = {"Accept": "text/html"}
# Stand-ins for greentechhub-ui's error templates: they print their context.
_PAGE = ("PAGE {code} msg={{{{ error_message|default('-') }}}} "
         "home={{{{ home_url|default('-') }}}} login={{{{ login_url|default('-') }}}} "
         "user={{{{ current_user|default('-') }}}}")
TEMPLATES = {
    "403.html": _PAGE.format(code=403),
    "404.html": _PAGE.format(code=404),
    "500.html": ("PAGE 500 ref={{ error_reference }} path={{ current_path }} home={{ home_url }} "
                 "nonce={{ csp_nonce or '-' }} user={{ current_user }} brand={{ brand }}"),
}


def _templates(*, broken_processor=False, broken_500=False) -> Jinja2Templates:
    pages = dict(TEMPLATES)
    if broken_500:
        pages["500.html"] = "{{ undefined_thing.boom() }}"
    env = Environment(loader=DictLoader(pages))
    env.globals["brand"] = "Svc"  # as greentechhub_ui.install() sets globals

    def processor(request):
        if broken_processor:
            raise RuntimeError("the database is down")
        return {"current_user": "alice"}

    return Jinja2Templates(env=env, context_processors=[processor])


def _app(settings, *, api_first=True, csp=False, broken_processor=False, broken_500=False,
         **kwargs):
    app = build_app(settings)
    templates = _templates(broken_processor=broken_processor, broken_500=broken_500)
    if api_first:
        register_api_error_handlers(app)
    register_error_pages(app, settings, templates=templates, **kwargs)
    if not api_first:
        register_api_error_handlers(app)
    if csp:
        register_csp(app)

    @app.get("/forbidden")
    async def forbidden():
        raise HTTPException(status_code=403)

    @app.get("/stocks/{code}")
    async def stock(code: str):
        raise NotFoundError("No such stock.")

    @app.get("/api/stocks/{code}")
    async def api_stock(code: str):
        raise NotFoundError("No such stock.")

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    @app.get("/api/boom")
    async def api_boom():
        raise RuntimeError("kaboom")

    @app.get("/teapot")
    async def teapot():
        raise HTTPException(status_code=418, detail="short and stout")

    @app.get("/private")
    async def private(user=Depends(require_page_identity("/login"))):
        return {"ok": True}

    return app


def _get(app, path, headers=HTML):
    async def go():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers, follow_redirects=False)

    return asyncio.run(go())


@pytest.mark.parametrize("api_first", [True, False])
def test_a_missing_page_gets_the_404_page_and_the_api_keeps_json(settings, api_first):
    app = _app(settings, api_first=api_first)
    page = _get(app, "/nope")
    assert page.status_code == 404 and page.text.startswith("PAGE 404 msg=-")
    assert "home=/ login=/login user=alice" in page.text  # context processors ran
    api = _get(app, "/api/nope")
    assert api.status_code == 404 and api.json()["code"] == "not_found"


def test_a_403_gets_the_page(settings):
    page = _get(_app(settings, home_url="/home", login_url="/signin"), "/forbidden")
    assert page.status_code == 403
    assert page.text == "PAGE 403 msg=- home=/home login=/signin user=alice"


def test_a_permission_denial_gets_the_403_page(settings):
    app = _app(settings)
    register_permissions(app, settings, roles=())

    @app.get("/admin")
    async def admin(user=Depends(require_page_permission("users.manage"))):
        return {}

    cookie = DevelopmentIdentityProvider(secret_key=settings.secret_key).issue(
        Identity(subject="bob", username="bob", email=None, groups=[], claims={}))
    denied = _get(app, "/admin", headers={**HTML, "Cookie": f"gth_session={cookie}"})
    assert denied.status_code == 403 and denied.text.startswith("PAGE 403")


def test_an_application_error_gets_the_page_with_its_message(settings):
    app = _app(settings)
    page = _get(app, "/stocks/XYZ")
    assert page.status_code == 404 and "msg=No such stock." in page.text
    api = _get(app, "/api/stocks/XYZ")
    assert api.status_code == 404 and api.json()["message"] == "No such stock."


@pytest.mark.parametrize("headers", [{**HTML, "HX-Request": "true"},
                                     {"Accept": "application/json"}])
def test_htmx_and_json_requests_keep_the_defaults(settings, headers):
    app = _app(settings)
    response = _get(app, "/nope", headers=headers)
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert _get(app, "/stocks/XYZ", headers=headers).json()["message"] == "No such stock."


def test_other_statuses_and_login_redirects_keep_the_defaults(settings):
    app = _app(settings)
    teapot = _get(app, "/teapot")
    assert teapot.status_code == 418 and teapot.json() == {"detail": "short and stout"}
    assert _get(app, "/private").status_code == 303


def test_an_unhandled_error_gets_the_500_page_with_its_reference(settings):
    app = _app(settings)
    page = _get(app, "/boom", headers={**HTML, "X-Request-ID": "req-42"})
    assert page.status_code == 500
    assert page.text == "PAGE 500 ref=req-42 path=/boom home=/ nonce=- user=None brand=Svc"
    generated = _get(app, "/boom")
    assert "ref=None" not in generated.text
    api = _get(app, "/api/boom")
    assert api.status_code == 500 and api.text == "Internal Server Error"


def test_the_500_page_doesnt_run_context_processors(settings):
    page = _get(_app(settings, broken_processor=True), "/boom")
    assert page.status_code == 500 and page.text.startswith("PAGE 500")


def test_a_broken_500_template_falls_back_to_plain_text(settings):
    page = _get(_app(settings, broken_500=True), "/boom")
    assert page.status_code == 500 and page.text == "Internal Server Error"


def test_the_500_page_gets_the_csp_nonce(settings):
    page = _get(_app(settings, csp=True), "/boom")
    nonce = page.text.split("nonce=")[1].split()[0]
    assert nonce != "-" and len(nonce) >= 20


def test_register_error_pages_must_run_before_the_app_starts(settings):
    app = _app(settings)
    _get(app, "/nope")
    with pytest.raises(RuntimeError, match="before the app starts"):
        register_error_pages(app, settings, templates=_templates())


def _request(path, headers):
    return Request({"type": "http", "path": path, "headers": [
        (k.lower().encode(), v.encode()) for k, v in headers.items()]})


def test_wants_error_page():
    assert wants_error_page(_request("/x", HTML))
    assert not wants_error_page(_request("/api/x", HTML))
    assert not wants_error_page(_request("/api", HTML))
    assert wants_error_page(_request("/apiary", HTML))
    assert wants_error_page(_request("/v1/x", HTML))
    assert not wants_error_page(_request("/v1/x", HTML), api_prefix="/v1")
    assert not wants_error_page(_request("/x", {**HTML, "HX-Request": "true"}))
    assert not wants_error_page(_request("/x", {"Accept": "application/json"}))
